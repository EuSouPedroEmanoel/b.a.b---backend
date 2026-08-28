import uuid
from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import DecodeError, ExpiredSignatureError, decode, encode
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import RevokedToken, User, UserRole
from src.settings import Settings

pwd_context = PasswordHash.recommended()
settings = Settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='auth/token')


def get_password_hash(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    to_encode = data.copy()

    expire = datetime.now(tz=ZoneInfo('UTC')) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update({'exp': expire, 'type': 'access'})

    encoded_jwt = encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

    return encoded_jwt


def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(tz=ZoneInfo('UTC')) + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )
    jti = str(uuid.uuid4())
    to_encode.update({'exp': expire, 'jti': jti, 'type': 'refresh'})
    encoded = encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded, jti, expire


def create_token_pair(username: str) -> tuple[str, str, str, datetime]:
    """Return (access_token, refresh_token, jti, refresh_expires_at)."""
    access = create_access_token(data={'sub': username})
    refresh, jti, exp = create_refresh_token(data={'sub': username})
    return access, refresh, jti, exp


async def _is_token_revoked(session: AsyncSession, jti: str) -> bool:
    result = await session.scalar(
        select(RevokedToken).where(RevokedToken.jti == jti)
    )
    return result is not None


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str = Depends(oauth2_scheme),
):
    credential_exception = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )

    try:  # noqa: PLW0717
        payload = decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        if payload.get('type') not in {None, 'access'}:
            # refresh tokens must not be used as access tokens
            raise credential_exception
        subject_username = payload.get('sub')
        if not subject_username:
            raise credential_exception
    except DecodeError:
        raise credential_exception

    except ExpiredSignatureError:
        raise credential_exception

    sttm = select(User).where(User.username == subject_username)
    user = await session.scalar(sttm)

    if not user:
        raise credential_exception

    if not user.is_active:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User is inactive',
        )

    return user


class RoleChecker:
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Not enough permissions',
            )
        return user


async def get_current_active_super_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Not enough permissions',
        )
    return user


async def get_current_school_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role not in {UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN}:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Not enough permissions',
        )
    return user


async def get_refresh_user(
    refresh_token: str,
    session: AsyncSession = Depends(get_session),
) -> User:
    credential_exception = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail='Invalid refresh token',
    )
    try:  # noqa: PLW0717
        payload = decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        if payload.get('type') != 'refresh':
            raise credential_exception
        jti = payload.get('jti')
        subject_username = payload.get('sub')
        if not jti or not subject_username:
            raise credential_exception
        if await _is_token_revoked(session, jti):
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED,
                detail='Refresh token revoked',
            )
    except ExpiredSignatureError:
        raise credential_exception
    except DecodeError:
        raise credential_exception

    user = await session.scalar(
        select(User).where(User.username == subject_username)
    )
    if not user or not user.is_active:
        raise credential_exception
    return user
