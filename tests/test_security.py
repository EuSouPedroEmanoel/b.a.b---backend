from http import HTTPStatus

from jwt import decode

from scr.security import create_access_token


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
