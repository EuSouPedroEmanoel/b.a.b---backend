from http import HTTPStatus

from freezegun import freeze_time


def test_get_token(client, user):
    response = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )

    token = response.json()

    assert response.status_code == HTTPStatus.OK
    assert token['token_type'] == 'Bearer'
    assert 'access_token' in token


def test_get_token_by_email(client, user):
    response = client.post(
        '/auth/token',
        data={'username': user.email, 'password': user.clean_password},
    )

    assert response.status_code == HTTPStatus.OK
    assert 'access_token' in response.json()


def test_get_token_by_cpf(client, school, school_admin, school_admin_token):
    resp = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'name': 'Aluno CPF',
            'cpf': '52998224725',
            'birthdate': '2015-05-10',
            'turma_numero': 6,
            'turma_letra': 'A',
            'password': 'S3cr3t!123',
        },
    )
    assert resp.status_code == HTTPStatus.CREATED

    login = client.post(
        '/auth/token',
        data={'username': '52998224725', 'password': 'S3cr3t!123'},
    )
    assert login.status_code == HTTPStatus.OK
    assert 'access_token' in login.json()


def test_raise_login_for_access_token_not_found_user(client):
    response = client.post(
        '/auth/token',
        data={
            'username': 'test',
            'password': 'usernoexists',
        },
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_raise_login_for_access_token_incorrect_password(client, user):
    response = client.post(
        '/auth/token',
        data={
            'username': f'{user.username}',
            'password': 'wrong password',
        },
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_token_expired_after_time(client, user):
    with freeze_time('2005-12-20 16:00:00'):
        response = client.post(
            '/auth/token',
            data={'username': user.username, 'password': user.clean_password},
        )
        assert response.status_code == HTTPStatus.OK
        token = response.json()['access_token']

    with freeze_time('2025-12-31 12:31:00'):
        response = client.put(
            f'/users/{user.id}',
            headers={'Authorization': f'Bearer {token}'},
            json={
                'username': 'wrongwrong',
                'email': 'wrong@wrong.com',
                'password': 'wrong',
            },
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {'detail': 'Could not validate credentials'}


def test_refresh_token(client, token):
    response = client.post(
        'auth/refresh_token', headers={'Authorization': f'Bearer {token}'}
    )

    data = response.json()

    assert response.status_code == HTTPStatus.OK
    assert 'access_token' in data
    assert 'token_type' in data


def test_token_expired_dont_refresh(client, user):
    with freeze_time('2023-07-14 12:00:00'):
        response = client.post(
            '/auth/token',
            data={'username': user.username, 'password': user.clean_password},
        )
        assert response.status_code == HTTPStatus.OK
        token = response.json()['access_token']

    with freeze_time('2023-07-14 12:31:00'):
        response = client.post(
            '/auth/refresh_token',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {'detail': 'Could not validate credentials'}


def test_refresh_expired_token(client, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.settings import Settings

    settings = Settings()
    expired = datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=10)
    token = encode(
        {
            'sub': user.username,
            'exp': expired,
            'type': 'refresh',
            'jti': 'jti-exp',
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = client.post('/auth/refresh', json={'refresh_token': token})
    assert resp.status_code == HTTPStatus.UNAUTHORIZED
    assert resp.json() == {'detail': 'Refresh token expired'}


def test_refresh_invalid_token_decode_error(client):
    resp = client.post(
        '/auth/refresh', json={'refresh_token': 'invalid.token.here'}
    )
    assert resp.status_code == HTTPStatus.UNAUTHORIZED
    assert resp.json() == {'detail': 'Invalid refresh token'}


def test_refresh_invalid_token_type(client, user):
    # use access_token as refresh_token
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    access = resp.json()['access_token']
    resp2 = client.post('/auth/refresh', json={'refresh_token': access})
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED
    assert resp2.json() == {'detail': 'Invalid token type'}


def test_refresh_missing_jti_or_sub(client):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.settings import Settings

    settings = Settings()
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    # missing jti
    token_no_jti = encode(
        {'sub': 'someuser', 'exp': exp, 'type': 'refresh'},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = client.post('/auth/refresh', json={'refresh_token': token_no_jti})
    assert resp.status_code == HTTPStatus.UNAUTHORIZED
    # missing sub
    token_no_sub = encode(
        {'jti': 'some-jti', 'exp': exp, 'type': 'refresh'},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp2 = client.post('/auth/refresh', json={'refresh_token': token_no_sub})
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED


def test_refresh_user_not_found_or_inactive(client, user):
    # get valid refresh, then deactivate user
    # Instead test via direct DB: we need session override. Use the session from conftest via client dependency.
    # Simplest: login then use refresh with non-existent user (encode manually)
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.settings import Settings

    settings = Settings()
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    token = encode(
        {
            'sub': 'nonexistent_user_xyz',
            'exp': exp,
            'type': 'refresh',
            'jti': 'jti-notfound',
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp2 = client.post('/auth/refresh', json={'refresh_token': token})
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED
    assert resp2.json()['detail'] == 'User not found or inactive'


def test_logout_invalid_token(client, user):
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    access = resp.json()['access_token']
    resp2 = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': 'invalid.token'},
    )
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED


def test_logout_expired_token(client, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.settings import Settings

    settings = Settings()
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    access = resp.json()['access_token']
    expired = datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=5)
    exp_token = encode(
        {
            'sub': user.username,
            'exp': expired,
            'type': 'refresh',
            'jti': 'jti-logout-exp',
            'iat': expired,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp2 = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': exp_token},
    )
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED


def test_logout_wrong_type(client, user):
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    access = resp.json()['access_token']
    # use access token as refresh
    resp2 = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': access},
    )
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED
    assert resp2.json()['detail'] == 'Invalid token type'


def test_logout_missing_jti_or_exp(client, user):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jwt import encode

    from src.settings import Settings

    settings = Settings()
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    access = resp.json()['access_token']
    exp = datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=30)
    token_no_jti = encode(
        {'sub': user.username, 'exp': exp, 'type': 'refresh'},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp2 = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': token_no_jti},
    )
    assert resp2.status_code == HTTPStatus.UNAUTHORIZED
    token_no_exp = encode(
        {'sub': user.username, 'jti': 'jti-no-exp', 'type': 'refresh'},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp3 = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': token_no_exp},
    )
    assert resp3.status_code == HTTPStatus.UNAUTHORIZED


def test_logout_already_logged_out(client, user):
    resp = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )
    tokens = resp.json()
    access = tokens['access_token']
    refresh = tokens['refresh_token']
    first = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': refresh},
    )
    assert first.status_code == HTTPStatus.OK
    assert first.json()['message'] == 'Logged out successfully'
    second = client.post(
        '/auth/logout',
        headers={'Authorization': f'Bearer {access}'},
        json={'refresh_token': refresh},
    )
    assert second.status_code == HTTPStatus.OK
    assert second.json()['message'] == 'Already logged out'
