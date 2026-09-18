from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AccountActivationAttempt,
    AccountActivationAudit,
    AccountActivationToken,
    AccountStatus,
    User,
)
from src.settings import Settings

ACTIVATION_ALPHABET = '123456789ABCDEFGHJKMNPQRSTUVWXYZ'
ACTIVATION_CODE_LENGTH = 9
MIN_ACTIVATION_PASSWORD_LENGTH = 8
GENERIC_ACTIVATION_ERROR = (
    'O código está inválido, expirado ou já foi utilizado.'
)

settings = Settings()


class ActivationError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def first_access_url(username: str, code: str) -> str:
    base_url = f'{settings.PUBLIC_WEB_URL.rstrip("/")}/primeiro-acesso'
    query = urlencode({'username': username, 'code': code})
    return f'{base_url}?{query}'


def normalize_activation_code(value: str) -> str:
    normalized = ''.join(
        char for char in value.upper() if char not in {' ', '-'}
    )
    if (
        len(normalized) != ACTIVATION_CODE_LENGTH
        or any(char not in ACTIVATION_ALPHABET for char in normalized)
    ):
        raise ActivationError(GENERIC_ACTIVATION_ERROR)
    return normalized


def format_activation_code(value: str) -> str:
    normalized = normalize_activation_code(value)
    return '-'.join(
        normalized[index:index + 3]
        for index in range(0, ACTIVATION_CODE_LENGTH, 3)
    )


def generate_activation_code() -> str:
    # secrets.choice uses SystemRandom and rejection sampling internally.
    raw = ''.join(
        secrets.choice(ACTIVATION_ALPHABET)
        for _ in range(ACTIVATION_CODE_LENGTH)
    )
    return format_activation_code(raw)


def _secret() -> bytes:
    return settings.ACTIVATION_HMAC_SECRET.get_secret_value().encode()


def activation_code_hash(code: str) -> bytes:
    normalized = normalize_activation_code(code)
    return hmac.new(_secret(), normalized.encode(), hashlib.sha256).digest()


def private_value_hash(value: str) -> bytes:
    return hmac.new(
        _secret(), value.strip().casefold().encode(), hashlib.sha256
    ).digest()


def verify_activation_hash(code: str, expected: bytes) -> bool:
    try:
        candidate = activation_code_hash(code)
    except ActivationError:
        candidate = hmac.new(_secret(), b'invalid', hashlib.sha256).digest()
    return hmac.compare_digest(candidate, expected)


def validate_activation_password(password: str) -> None:
    if (
        len(password) < MIN_ACTIVATION_PASSWORD_LENGTH
        or not any(char.isalpha() for char in password)
        or not any(char.isdigit() for char in password)
    ):
        raise ActivationError(
            'A senha deve ter ao menos 8 caracteres, uma letra e um número.'
        )


async def generate_invitation(
    session: AsyncSession,
    user: User,
    actor_id: int,
    *,
    event: str = 'issued',
) -> tuple[AccountActivationToken, str]:
    now = utcnow()
    await session.execute(
        update(AccountActivationToken)
        .where(
            AccountActivationToken.user_id == user.id,
            AccountActivationToken.used_at.is_(None),
            AccountActivationToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    code = generate_activation_code()
    invitation = AccountActivationToken(
        user_id=user.id,
        code_hash=activation_code_hash(code),
        expires_at=now + timedelta(days=settings.ACTIVATION_EXPIRE_DAYS),
        created_by=actor_id,
    )
    session.add(invitation)
    session.add(
        AccountActivationAudit(
            user_id=user.id,
            actor_id=actor_id,
            event=event,
        )
    )
    await session.flush()
    return invitation, code


async def generate_invitations(
    session: AsyncSession,
    users: list[User],
    actor_id: int,
) -> list[tuple[User, AccountActivationToken, str]]:
    results = []
    for user in users:
        invitation, code = await generate_invitation(
            session, user, actor_id
        )
        results.append((user, invitation, code))
    return results


async def active_invitation(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> AccountActivationToken | None:
    query = (
        select(AccountActivationToken)
        .where(
            AccountActivationToken.user_id == user_id,
            AccountActivationToken.used_at.is_(None),
            AccountActivationToken.revoked_at.is_(None),
        )
        .order_by(AccountActivationToken.created_at.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def _too_many_attempts(
    session: AsyncSession,
    username_hash: bytes,
    origin_hash: bytes,
) -> bool:
    since = utcnow() - timedelta(
        minutes=settings.ACTIVATION_ATTEMPT_WINDOW_MINUTES
    )
    user_failures = await session.scalar(
        select(func.count(AccountActivationAttempt.id)).where(
            AccountActivationAttempt.username_hash == username_hash,
            AccountActivationAttempt.success.is_(False),
            AccountActivationAttempt.created_at >= since,
        )
    )
    origin_failures = await session.scalar(
        select(func.count(AccountActivationAttempt.id)).where(
            AccountActivationAttempt.origin_hash == origin_hash,
            AccountActivationAttempt.success.is_(False),
            AccountActivationAttempt.created_at >= since,
        )
    )
    return (
        (user_failures or 0) >= settings.ACTIVATION_USER_ATTEMPTS
        or (origin_failures or 0) >= settings.ACTIVATION_ORIGIN_ATTEMPTS
    )


async def verify_invitation(  # noqa: PLR0913
    session: AsyncSession,
    username: str,
    code: str,
    origin: str,
    *,
    event: str,
    for_update: bool = False,
) -> tuple[User, AccountActivationToken]:
    username_key = private_value_hash(username)
    origin_key = private_value_hash(origin or 'unknown')
    now = utcnow()
    if await _too_many_attempts(session, username_key, origin_key):
        raise ActivationError(GENERIC_ACTIVATION_ERROR)

    query = select(User).where(
        func.lower(User.username) == username.strip().lower()
    )
    if for_update:
        query = query.with_for_update()
    user = await session.scalar(query)
    invitation = (
        await active_invitation(session, user.id, for_update=for_update)
        if user
        else None
    )
    valid = bool(
        user
        and user.account_status == AccountStatus.PENDING_ACTIVATION
        and user.is_active
        and invitation
        and invitation.expires_at > now
        and (
            invitation.locked_until is None
            or invitation.locked_until <= now
        )
        and verify_activation_hash(code, invitation.code_hash)
    )
    session.add(
        AccountActivationAttempt(
            username_hash=username_key,
            origin_hash=origin_key,
            user_id=user.id if user else None,
            success=valid,
            event=event,
        )
    )
    if not valid:
        if invitation:
            failures = await session.scalar(
                select(func.count(AccountActivationAttempt.id)).where(
                    AccountActivationAttempt.username_hash == username_key,
                    AccountActivationAttempt.success.is_(False),
                    AccountActivationAttempt.created_at
                    >= now - timedelta(
                        minutes=settings.ACTIVATION_ATTEMPT_WINDOW_MINUTES
                    ),
                )
            )
            if (failures or 0) >= settings.ACTIVATION_USER_ATTEMPTS:
                invitation.locked_until = now + timedelta(
                    minutes=settings.ACTIVATION_LOCK_MINUTES
                )
        await session.flush()
        raise ActivationError(GENERIC_ACTIVATION_ERROR)
    await session.flush()
    return user, invitation
