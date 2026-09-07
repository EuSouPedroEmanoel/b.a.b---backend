import pytest
from pydantic import ValidationError

from src.settings import Settings
from src.utils.cpf import (
    CPF_COLLISION_GUARD_DOMAIN,
    CPF_LOOKUP_DOMAIN,
    classify_cpf_candidates,
    cpf_collision_guard,
    cpf_last2,
    cpf_lookup_digest,
    mask_cpf_last2,
    normalize_cpf,
    validate_cpf,
)


def test_normalize_and_validate_formatted_cpf():
    assert normalize_cpf('529.982.247-25') == '52998224725'
    assert validate_cpf('529.982.247-25')


def test_lookup_digest_is_deterministic_and_secret_bound(monkeypatch):
    cpf = '52998224725'
    first = cpf_lookup_digest(cpf)
    first_guard = cpf_collision_guard(cpf)
    assert first == cpf_lookup_digest('529.982.247-25')
    assert first_guard == cpf_collision_guard('529.982.247-25')
    assert first != cpf_lookup_digest('11144477735')
    assert first_guard != cpf_collision_guard('11144477735')

    monkeypatch.setenv('CPF_HMAC_SECRET', 'a-different-test-secret-value')
    assert first != cpf_lookup_digest(cpf)


def test_lookup_and_collision_guard_use_separate_domains():
    cpf = '52998224725'
    assert cpf_lookup_digest(cpf) != cpf_collision_guard(cpf)
    assert CPF_LOOKUP_DOMAIN != CPF_COLLISION_GUARD_DOMAIN


def test_collision_candidates_are_not_classified_as_duplicates():
    duplicate, collisions = classify_cpf_candidates(
        [(10, b'guard-a'), (11, b'guard-b')], b'guard-b'
    )
    assert duplicate
    assert collisions == [10]


def test_mask_uses_only_last_two_digits():
    assert cpf_last2('529.982.247-25') == '25'
    assert mask_cpf_last2('25') == '•••.•••.•••-25'
    assert mask_cpf_last2(None) is None


def test_lookup_digest_rejects_invalid_cpf():
    with pytest.raises(ValueError, match='CPF inválido'):
        cpf_lookup_digest('11111111111')


def test_secret_is_required(monkeypatch):
    monkeypatch.delenv('CPF_HMAC_SECRET', raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
