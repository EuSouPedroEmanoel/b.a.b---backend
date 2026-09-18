import asyncio
from datetime import timedelta
from http import HTTPStatus

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.models import (
    AccountActivationAttempt,
    AccountActivationAudit,
    AccountActivationToken,
    AccountStatus,
    User,
)
from src.routers.account_activation import (
    _complete_activation,  # noqa: PLC2701
)
from src.schemas import ActivationComplete
from src.services.account_activation import (
    ACTIVATION_ALPHABET,
    ActivationError,
    activation_code_hash,
    format_activation_code,
    generate_activation_code,
    normalize_activation_code,
    utcnow,
)


def student_payload(cpf='11144477735'):
    return {
        'name': 'Primeiro Acesso',
        'cpf': cpf,
        'birthdate': '2015-05-10',
        'turma_numero': 7,
        'turma_letra': 'A',
    }


def create_pending_student(client, token, cpf='11144477735'):
    response = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {token}'},
        json=student_payload(cpf),
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json()


def test_activation_code_uses_exact_custom_alphabet_and_format():
    generated = [generate_activation_code() for _ in range(200)]
    assert all(len(code) == 11 for code in generated)
    assert all(code[3] == code[7] == '-' for code in generated)
    compact = ''.join(generated).replace('-', '')
    assert set(compact) <= set(ACTIVATION_ALPHABET)
    assert not {'0', 'O', 'I', 'L'} & set(compact)
    assert len(set(generated)) == len(generated)


def test_activation_code_normalization_and_rejection():
    assert normalize_activation_code('abc-123-xyz') == 'ABC123XYZ'
    assert normalize_activation_code(' a b c 1 2 3 x y z ') == 'ABC123XYZ'
    assert format_activation_code('abc123xyz') == 'ABC-123-XYZ'
    for invalid in ['ABC-120-XYZ', 'ABC-12O-XYZ', 'ABC-1I3-XYZ', 'ABC-1L3-XYZ', 'ABC_123_XYZ']:
        with pytest.raises(ActivationError):
            normalize_activation_code(invalid)


@pytest.mark.asyncio
async def test_creation_stores_hash_only_and_pending_blocks_login(
    client, session, school_admin_token
):
    created = create_pending_student(client, school_admin_token)
    code = created['activation_invitation']['code']
    user = await session.scalar(
        select(User).where(User.username == created['username'])
    )
    invitation = await session.scalar(
        select(AccountActivationToken).where(
            AccountActivationToken.user_id == user.id
        )
    )
    assert user.account_status == AccountStatus.PENDING_ACTIVATION
    assert user.password is None
    assert invitation.code_hash == activation_code_hash(code)
    assert code.encode() not in invitation.code_hash
    login = client.post(
        '/auth/token', data={'username': user.username, 'password': code}
    )
    assert login.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_validate_complete_single_use_and_audit(
    client, session, school_admin_token
):
    created = create_pending_student(client, school_admin_token)
    credentials = {
        'username': created['username'],
        'code': created['activation_invitation']['code'],
    }
    valid = client.post('/account-activation/validate', json=credentials)
    assert valid.status_code == HTTPStatus.OK
    complete = client.post(
        '/account-activation/complete',
        json={
            **credentials,
            'password': 'SenhaSegura123',
            'password_confirmation': 'SenhaSegura123',
        },
    )
    assert complete.status_code == HTTPStatus.OK
    reused = client.post('/account-activation/validate', json=credentials)
    assert reused.status_code == HTTPStatus.BAD_REQUEST
    user = await session.scalar(
        select(User).where(User.username == created['username'])
    )
    await session.refresh(user)
    assert user.account_status == AccountStatus.ACTIVE
    assert user.activated_at is not None
    invitation = await session.scalar(
        select(AccountActivationToken).where(
            AccountActivationToken.user_id == user.id
        )
    )
    assert invitation.used_at is not None
    events = list((await session.scalars(
        select(AccountActivationAudit.event).where(
            AccountActivationAudit.user_id == user.id
        )
    )).all())
    assert events == ['issued', 'activated']
    attempts = list((await session.scalars(
        select(AccountActivationAttempt).where(
            AccountActivationAttempt.user_id == user.id
        )
    )).all())
    assert all(not hasattr(attempt, 'code') for attempt in attempts)


@pytest.mark.asyncio
async def test_expiration_revocation_reissue_and_print(
    client, session, school_admin_token
):
    created = create_pending_student(client, school_admin_token)
    user = await session.scalar(
        select(User).where(User.username == created['username'])
    )
    invitation = await session.scalar(
        select(AccountActivationToken).where(
            AccountActivationToken.user_id == user.id
        )
    )
    invitation.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    expired = client.post(
        '/account-activation/validate',
        json={
            'username': user.username,
            'code': created['activation_invitation']['code'],
        },
    )
    assert expired.status_code == HTTPStatus.BAD_REQUEST

    regenerated = client.post(
        f'/users/{user.id}/activation/regenerate',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert regenerated.status_code == HTTPStatus.OK
    new_invitation = regenerated.json()
    assert new_invitation['code'] != created['activation_invitation']['code']
    assert f"username={user.username}" in new_invitation['first_access_url']
    assert f"code={new_invitation['code']}" in new_invitation['first_access_url']
    await session.refresh(invitation)
    assert invitation.revoked_at is not None

    printed = client.post(
        new_invitation['print_url'],
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'username': user.username, 'code': new_invitation['code']},
    )
    assert printed.status_code == HTTPStatus.OK
    assert 'Primeiro acesso à Biblioteca' in printed.text
    assert new_invitation['code'] in printed.text
    assert '<div class="qr-wrap">' in printed.text
    assert '<svg' in printed.text
    assert printed.headers['cache-control'] == 'no-store, private'

    revoked = client.post(
        f'/users/{user.id}/activation/revoke',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert revoked.status_code == HTTPStatus.OK
    rejected = client.post(
        '/account-activation/validate',
        json={'username': user.username, 'code': new_invitation['code']},
    )
    assert rejected.status_code == HTTPStatus.BAD_REQUEST


def test_validation_is_generic_for_unknown_user_and_bad_code(client):
    unknown = client.post(
        '/account-activation/validate',
        json={'username': 'nao-existe', 'code': 'ABC-123-XYZ'},
    )
    invalid = client.post(
        '/account-activation/validate',
        json={'username': 'nao-existe', 'code': 'ABC-120-XYZ'},
    )
    assert unknown.status_code == invalid.status_code == HTTPStatus.BAD_REQUEST
    assert unknown.json() == invalid.json()


def test_attempt_limit_temporarily_blocks_even_a_correct_code(
    client, school_admin_token
):
    created = create_pending_student(client, school_admin_token)
    for _ in range(5):
        response = client.post(
            '/account-activation/validate',
            json={'username': created['username'], 'code': 'ABC-123-XYZ'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
    blocked = client.post(
        '/account-activation/validate',
        json={
            'username': created['username'],
            'code': created['activation_invitation']['code'],
        },
    )
    assert blocked.status_code == HTTPStatus.BAD_REQUEST
    assert 'tentativa' not in blocked.text.lower()


@pytest.mark.asyncio
async def test_two_simultaneous_completions_only_activate_once(
    client, engine, school_admin_token
):
    created = create_pending_student(client, school_admin_token)
    payload = ActivationComplete(
        username=created['username'],
        code=created['activation_invitation']['code'],
        password='Concorrente123',
        password_confirmation='Concorrente123',
    )
    request = Request(
        {'type': 'http', 'method': 'POST', 'path': '/', 'headers': []}
    )
    async with (
        AsyncSession(engine, expire_on_commit=False) as first_session,
        AsyncSession(engine, expire_on_commit=False) as second_session,
    ):
        results = await asyncio.gather(
            _complete_activation(payload, request, first_session),
            _complete_activation(payload, request, second_session),
            return_exceptions=True,
        )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ActivationError) for result in results) == 1
