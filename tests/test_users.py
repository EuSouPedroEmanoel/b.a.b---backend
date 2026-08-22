from http import HTTPStatus

from scr.schemas import UserPublic


def test_create_user(client, school, super_admin_token):
    response = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'alice',
            'email': 'alice@exemple.com',
            'password': 'S3cr3t!123',
            'role': 'librarian',
            'school_id': school.id,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['username'] == 'alice'
    assert response.json()['email'] == 'alice@exemple.com'
    assert response.json()['school_id'] == school.id


def test_create_user_integraty(client, school, super_admin_token):
    client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'password': 'secret',
            'role': 'librarian',
            'school_id': school.id,
        },
    )

    actual_update = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'fausto',
            'email': 'bob@exemple.lol',
            'password': 'newsecret',
            'role': 'librarian',
            'school_id': school.id,
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


def test_read_user_by_id(client, user, token):
    response = client.get(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == UserPublic.model_validate(user).model_dump()


def test_raise_read_user_by_id(client, user, token):
    response = client.get(
        '/users/9999',
        headers={'Authorization': f'Bearer {token}'},
    )

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
    data = response.json()
    assert data['username'] == 'Pedro'
    assert data['email'] == 'pedro@email.ai'
    assert data['id'] == user.id
    assert data['role'] == user.role
    assert data['school_id'] == user.school_id


def test_update_integrity_error(
    client, user, token, school, super_admin_token
):
    client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'password': 'secret',
            'role': 'librarian',
            'school_id': school.id,
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
