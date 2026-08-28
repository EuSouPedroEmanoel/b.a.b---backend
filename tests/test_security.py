from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from jwt import decode, encode

from src.models import UserRole
from src.security import (
    RoleChecker,
    create_access_token,
    get_current_active_super_admin,
    get_current_school_admin,
    get_password_hash,
    verify_password,
)
from src.settings import Settings


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


@pytest.mark.asyncio
async def test_is_token_revoked(session):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from src.models import RevokedToken
    from src.security import _is_token_revoked  # noqa: PLC2701

    jti = 'test-jti-revoked'
    assert await _is_token_revoked(session, jti) is False
    rt = RevokedToken(
        jti=jti,
        expires_at=datetime.now(tz=ZoneInfo('UTC')) + timedelta(hours=1),
    )
    session.add(rt)
    await session.commit()
    assert await _is_token_revoked(session, jti) is True


def test_refresh_token_as_access_forbidden(client, user):
    # login to get refresh, try to use refresh as Bearer
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    refresh = resp.json()['refresh_token']
    # try to access protected endpoint with refresh token
    resp2 = client.get(
        '/users/', headers={'Authorization': f'Bearer {refresh}'}
    )
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED
    assert resp2.json()['detail'] == 'Could not validate credentials'


@pytest.mark.asyncio
async def test_get_refresh_user_success(session, user):
    from src.security import create_token_pair, get_refresh_user

    # create token pair for user
    _access, refresh, jti, exp = create_token_pair(user.username)
    result = await get_refresh_user(refresh, session)
    assert result.username == user.username


@pytest.mark.asyncio
async def test_get_refresh_user_invalid_type(session, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.security import get_refresh_user
    from src.settings import Settings

    settings = Settings()
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    token = encode(
        {
            'sub': user.username,
            'exp': exp,
            'type': 'access',
            'jti': 'jti-access',
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        await get_refresh_user(token, session)
    assert exc.value.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_refresh_user_missing_jti(session, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.security import get_refresh_user
    from src.settings import Settings

    settings = Settings()
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    token = encode(
        {'sub': user.username, 'exp': exp, 'type': 'refresh'},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(HTTPException):
        await get_refresh_user(token, session)


@pytest.mark.asyncio
async def test_get_refresh_user_revoked(session, user):

    from src.models import RevokedToken
    from src.security import create_token_pair, get_refresh_user

    _access, refresh, jti, exp = create_token_pair(user.username)
    # revoke
    session.add(RevokedToken(jti=jti, expires_at=exp))
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await get_refresh_user(refresh, session)
    assert 'revoked' in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_get_refresh_user_expired(session, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.security import get_refresh_user
    from src.settings import Settings

    settings = Settings()
    expired = datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=5)
    token = encode(
        {
            'sub': user.username,
            'exp': expired,
            'type': 'refresh',
            'jti': 'jti-exp2',
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(HTTPException):
        await get_refresh_user(token, session)


@pytest.mark.asyncio
async def test_get_refresh_user_invalid_token(session):
    from src.security import get_refresh_user

    with pytest.raises(HTTPException):
        await get_refresh_user('invalid.token', session)


@pytest.mark.asyncio
async def test_get_refresh_user_not_found(session):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.security import get_refresh_user
    from src.settings import Settings

    settings = Settings()
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    token = encode(
        {
            'sub': 'ghost_user_123',
            'exp': exp,
            'type': 'refresh',
            'jti': 'jti-ghost',
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(HTTPException):
        await get_refresh_user(token, session)


@pytest.mark.asyncio
async def test_get_refresh_user_inactive(session, user):

    from src.security import create_token_pair, get_refresh_user

    _access, refresh, jti, exp = create_token_pair(user.username)
    user.is_active = False
    session.add(user)
    await session.commit()
    with pytest.raises(HTTPException):
        await get_refresh_user(refresh, session)
