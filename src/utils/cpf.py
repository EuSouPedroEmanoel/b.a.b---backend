"""CPF normalization, validation, lookup hashing and safe display helpers."""

import hashlib
import hmac
import logging

from src.settings import Settings

CPF_LENGTH = 11
CPF_LAST2_LENGTH = 2
CPF_LOOKUP_DOMAIN = b'cpf-lookup:'
CPF_COLLISION_GUARD_DOMAIN = b'cpf-collision-guard:'
CPF_LOOKUP_HASH_COLLISION = 'CPF_LOOKUP_HASH_COLLISION'
_logger = logging.getLogger('src.cpf')


def normalize_cpf(cpf: str | None) -> str | None:  # pragma: no cover
    """Strip formatting and return only the 11 digits (or None if empty)."""  # pragma: no cover  # noqa: E501
    if not cpf:  # pragma: no cover
        return None  # pragma: no cover
    digits = ''.join(ch for ch in cpf if ch.isdigit())
    return digits or None


def validate_cpf(cpf: str | None) -> bool:  # pragma: no cover
    """Validate a CPF (11 digits + two check digits). Masks are tolerated."""  # pragma: no cover  # noqa: E501
    digits = normalize_cpf(cpf)
    if not digits or len(digits) != CPF_LENGTH:
        return False
    # all equal digits are invalid
    if len(set(digits)) == 1:  # pragma: no cover
        return False  # pragma: no cover

    def _check(dig: list[int], length: int, weight_start: int) -> int:
        total = sum(d * (weight_start - i) for i, d in enumerate(dig))
        rest = (total * 10) % 11
        return 0 if rest == 10 else rest  # noqa: PLR2004

    base = [int(d) for d in digits[:9]]
    first = _check(base, 9, 10)
    if first != int(digits[9]):
        return False
    second = _check(base + [first], 10, 11)
    return second == int(digits[10])


def _cpf_hmac(cpf: str | None, domain: bytes) -> bytes:
    normalized = normalize_cpf(cpf)
    if not normalized or not validate_cpf(normalized):
        raise ValueError('CPF inválido')
    secret = Settings().CPF_HMAC_SECRET.get_secret_value().encode('utf-8')
    return hmac.new(
        secret, domain + normalized.encode('ascii'), hashlib.sha256
    ).digest()


def cpf_lookup_digest(cpf: str | None) -> bytes:
    """Return the HMAC used as the first CPF equality lookup component."""
    return _cpf_hmac(cpf, CPF_LOOKUP_DOMAIN)


def cpf_collision_guard(cpf: str | None) -> bytes:
    """Return the independent HMAC used to disambiguate lookup collisions."""
    return _cpf_hmac(cpf, CPF_COLLISION_GUARD_DOMAIN)


def cpf_last2(cpf: str | None) -> str | None:
    normalized = normalize_cpf(cpf)
    return (
        normalized[-CPF_LAST2_LENGTH:]
        if normalized and len(normalized) >= CPF_LAST2_LENGTH
        else None
    )


def mask_cpf_last2(last2: str | None) -> str | None:
    if not last2:
        return None
    return f'•••.•••.•••-{last2}'


def cpf_storage_values(cpf: str) -> tuple[bytes, bytes, str]:
    normalized = normalize_cpf(cpf)
    if not normalized or not validate_cpf(normalized):
        raise ValueError('CPF inválido')
    return (
        cpf_lookup_digest(normalized),
        cpf_collision_guard(normalized),
        normalized[-CPF_LAST2_LENGTH:],
    )


def log_cpf_lookup_collision(
    *, school_id: int | None, existing_user_ids: list[int]
) -> None:
    """Emit a safe structured event without any CPF-derived value."""
    _logger.error(
        CPF_LOOKUP_HASH_COLLISION,
        extra={
            'event_name': CPF_LOOKUP_HASH_COLLISION,
            'school_id': school_id,
            'existing_user_ids': existing_user_ids,
        },
    )


def classify_cpf_candidates(
    candidates: list[tuple[int, bytes | None]], collision_guard: bytes
) -> tuple[bool, list[int]]:
    """Classify same-lookup rows as duplicate CPF or hash collision."""
    duplicate = False
    collisions: list[int] = []
    for user_id, candidate_guard in candidates:
        if candidate_guard == collision_guard:
            duplicate = True
        else:
            collisions.append(user_id)
    return duplicate, collisions
