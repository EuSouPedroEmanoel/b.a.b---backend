"""CPF helpers: normalization and checksum validation (no external deps)."""

CPF_LENGTH = 11


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
