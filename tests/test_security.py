from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from jwt import decode, encode

from scr.models import UserRole
from scr.security import (
    RoleChecker,
    create_access_token,
    get_current_active_super_admin,
    get_current_school_admin,
    get_password_hash,
    verify_password,
)
from scr.settings import Settings


def test_jwt(settings):
    data = {'sub': 'test_user'}
    token = create_access_token(data)

    decoded = decode(token, settings.SECRET_KEY, settings.ALGORITHM)

    assert decoded['sub'] == data['sub']
    assert 'exp' in decoded


def test_jwt_invalid_token(client):
    response = client.delete(
        '/users/1', headers={'Authorization': 'Bearer token-invalido'}
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Could not validate credentials'}
    assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_get_current_user_not_found(client):
    token_invalido = create_access_token(data={'sub': 'usuario_fantasma_123'})

    headers = {'Authorization': f'Bearer {token_invalido}'}
    response = client.get('/users/', headers=headers)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Could not validate credentials'}
    assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_get_current_user_without_username(client):
    token_invalido = create_access_token(data={})

    headers = {'Authorization': f'Bearer {token_invalido}'}
    response = client.get('/users/', headers=headers)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Could not validate credentials'}
    assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_get_current_user_expired_token(client):
    settings = Settings()
    expired = datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=10)
    token = encode(
        {'sub': 'test_user', 'exp': expired},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    headers = {'Authorization': f'Bearer {token}'}
    response = client.get('/users/', headers=headers)
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_verify_password_and_hash():
    hashed = get_password_hash('secret123')
    assert verify_password('secret123', hashed) is True
    assert verify_password('wrong', hashed) is False


@pytest.mark.asyncio
async def test_role_checker_allowed(user):
    checker = RoleChecker([UserRole.LIBRARIAN, UserRole.SCHOOL_ADMIN])
    result = await checker(user)
    assert result == user


@pytest.mark.asyncio
async def test_role_checker_forbidden(user):
    checker = RoleChecker([UserRole.SUPER_ADMIN])
    with pytest.raises(HTTPException) as exc:
        await checker(user)
    assert exc.value.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_get_current_active_super_admin_success(super_admin):
    result = await get_current_active_super_admin(super_admin)
    assert result == super_admin


@pytest.mark.asyncio
async def test_get_current_active_super_admin_forbidden(user):
    with pytest.raises(HTTPException) as exc:
        await get_current_active_super_admin(user)
    assert exc.value.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_get_current_school_admin_success_super_admin(super_admin):
    result = await get_current_school_admin(super_admin)
    assert result == super_admin


@pytest.mark.asyncio
async def test_get_current_school_admin_success_school_admin(school_admin):
    result = await get_current_school_admin(school_admin)
    assert result == school_admin


@pytest.mark.asyncio
async def test_get_current_school_admin_forbidden(user):
    with pytest.raises(HTTPException) as exc:
        await get_current_school_admin(user)
    assert exc.value.status_code == HTTPStatus.FORBIDDEN
