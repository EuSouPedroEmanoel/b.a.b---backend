from http import HTTPStatus

from scr.schemas import UserPublic


def test_create_user(client):

    response = client.post(
        '/users/',
        json={
            'username': 'alice',
            'email': 'alice@exemple.com',
            'password': 'S3cr3t!123',
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json() == {
        'id': 1,
        'username': 'alice',
        'email': 'alice@exemple.com',
    }


def test_create_user_integraty(client):
    client.post(
        '/users/',
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'password': 'secret',
        },
    )

    actual_update = client.post(
        '/users/',
        json={
            'username': 'fausto',
            'email': 'bob@exemple.lol',
            'password': 'newsecret',
        },
    )

    assert actual_update.status_code == HTTPStatus.CONFLICT
    assert actual_update.json() == {
        'detail': 'Username or Email already exists!!'
    }


def test_read_users(client, user, token):

    user_schema = UserPublic.model_validate(user).model_dump()
    response = client.get(
        '/users/', headers={'Authorization': f'Bearer {token}'}
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'users': [user_schema]}


def test_read_user_by_id(client, user):
    response = client.get(f'/users/{user.id}')

    assert response.status_code == HTTPStatus.OK
    assert response.json() == UserPublic.model_validate(user).model_dump()


def test_raise_read_user_by_id(client):
    response = client.get('/users/1')

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'User Not Found...'}


def test_update_user(client, user, token):
    response = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'username': 'Pedro',
            'email': 'pedro@email.ai',
            'password': 'secret',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        'username': 'Pedro',
        'email': 'pedro@email.ai',
        'id': 1,
    }


def test_update_integrity_error(client, user, token):
    client.post(
        '/users',
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'password': 'secret',
        },
    )

    actual_update = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'username': 'fausto',
            'email': 'bob@exemple.lol',
            'password': 'newsecret',
        },
    )

    assert actual_update.status_code == HTTPStatus.CONFLICT
    assert actual_update.json() == {
        'detail': 'Username or Email already exists!!'
    }


def test_delete_user(client, user, token):
    response = client.delete(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'message': 'User Deleted'}


def test_raise_delete_user_forbidden(client, other_user, token):
    response = client.delete(
        f'/users/{other_user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_raise_update_user_forbidden(client, other_user, token):
    response = client.put(
        f'/users/{other_user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'username': 'Pedro',
            'email': 'blablabla@email.com',
            'password': 'senha',
        },
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
