from datetime import date
from http import HTTPStatus

import pytest
from sqlalchemy import select

from src.models import User


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_privacy_profile_is_limited_to_authenticated_user(client, token):
    response = client.get('/privacy/me', headers=_headers(token))
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert set(body) == {
        'account',
        'library',
        'preferences',
        'security',
        'sharing',
        'correction_guidance',
        'preservation',
    }
    assert 'password' not in body['account']
    assert 'tokens' in body['security']


@pytest.mark.asyncio
async def test_privacy_export_requires_current_password(
    client, token, session, user
):
    current = await session.scalar(select(User).where(User.id == user.id))
    assert current is not None
    current.birthdate = date(2010, 1, 2)
    await session.commit()

    invalid = client.post(
        '/privacy/me/export',
        headers=_headers(token),
        json={'password': 'wrong-password'},
    )
    assert invalid.status_code == HTTPStatus.UNAUTHORIZED

    valid = client.post(
        '/privacy/me/export',
        headers=_headers(token),
        json={'password': 'testteste'},
    )
    assert valid.status_code == HTTPStatus.OK
    body = valid.json()
    assert body['export_version'] == '1.0'
    assert body['data']['account']['birthdate'] == '2010-01-02'
    assert 'password' not in str(body)


@pytest.mark.asyncio
async def test_privacy_request_lifecycle_and_school_scope(
    client, token, school_admin_token, other_school
):
    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction', 'description': 'Nome'},
    )
    assert created.status_code == HTTPStatus.CREATED
    request_id = created.json()['id']

    mine = client.get('/privacy/me/requests', headers=_headers(token))
    assert mine.status_code == HTTPStatus.OK
    assert mine.json()['items'][0]['id'] == request_id

    policy = client.get(
        f'/privacy/schools/{other_school.id}/policy',
        headers=_headers(school_admin_token),
    )
    assert policy.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_privacy_requests_require_privacy_operator(client, token):
    response = client.get('/privacy/requests', headers=_headers(token))
    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_automatic_anonymization_revokes_account(
    client, session, token, user
):
    response = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['status'] == 'fulfilled'

    current = await session.scalar(select(User).where(User.id == user.id))
    assert current is not None
    assert current.name == 'Titular anonimizado'
    assert current.password is None
    assert current.is_active is False
