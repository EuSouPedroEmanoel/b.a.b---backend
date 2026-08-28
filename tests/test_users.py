from http import HTTPStatus

from src.schemas import UserPublic


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
    assert response.json()['items'] == [user_schema]
    assert response.json()['total'] == 1


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
    assert response.json() == {'message': 'User deactivated'}


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


def test_create_user_school_admin_ignores_school_id(
    client, school, school_admin, school_admin_token, other_school
):
    # school_admin creates user, should auto-assign own school even if payload has other_school.id
    resp = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'username': 'staff_by_admin',
            'email': 'staff_by_admin@ex.com',
            'password': 'secret123',
            'role': 'librarian',
            'school_id': other_school.id,
        },
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert resp.json()['school_id'] == school_admin.school_id
    assert resp.json()['school_id'] != other_school.id


def test_create_user_super_admin_missing_school_id(client, super_admin_token):
    resp = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'no_school_user',
            'email': 'no_school@ex.com',
            'password': 'secret123',
            'role': 'librarian',
        },
    )
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert 'school_id is required' in resp.json()['detail']


def test_create_user_invalid_role(client, school, super_admin_token):
    resp = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'invalid_role_user',
            'email': 'invalid_role@ex.com',
            'password': 'secret123',
            'role': 'super_admin',
            'school_id': school.id,
        },
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_list_users_without_school_forbidden(client):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake = User(
        username='noschool_users',
        email='noschool_users@ex.com',
        password='h',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake.id = 9990

    async def fake_user():
        return fake

    app.dependency_overrides[get_current_user] = fake_user
    try:
        resp = client.get('/users/', headers={'Authorization': 'Bearer fake'})
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


def test_read_user_by_id_cross_school_not_found(
    client, user, token, other_school, session
):
    from src.models import User, UserRole
    from src.security import get_password_hash

    other_user = User(
        username='cross_school_user',
        email='cross_school@ex.com',
        password=get_password_hash('secret'),
        role=UserRole.LIBRARIAN,
        school_id=other_school.id,
    )
    session.add(other_user)

    import asyncio

    async def _commit():
        await session.commit()
        await session.refresh(other_user)

    asyncio.run(_commit())
    resp = client.get(
        f'/users/{other_user.id}', headers={'Authorization': f'Bearer {token}'}
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_create_book_empty_title(client, token):
    resp = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={'title': '', 'description': 'desc'},
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_create_student(client, school, school_admin, school_admin_token):
    resp = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'name': 'João da Silva',
            'cpf': '52998224725',
            'birthdate': '2015-05-10',
            'turma_numero': 7,
            'turma_letra': 'A',
            'password': 'S3cr3t!123',
        },
    )

    assert resp.status_code == HTTPStatus.CREATED
    data = resp.json()
    assert data['role'] == 'student'
    assert data['cpf'] == '52998224725'
    assert data['birthdate'] == '2015-05-10'
    assert data['turma_numero'] == 7
    assert data['turma_letra'] == 'A'
    assert data['email'] is None
    assert data['school_id'] == school_admin.school_id


def test_create_student_default_password_is_birthdate(
    client, school_admin_token
):
    resp = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'name': 'Maria',
            'cpf': '11144477735',
            'birthdate': '2015-05-10',
            'turma_numero': 7,
            'turma_letra': 'A',
        },
    )

    assert resp.status_code == HTTPStatus.CREATED
    username = resp.json()['username']

    login = client.post(
        '/auth/token',
        data={'username': username, 'password': '10052015'},
    )
    assert login.status_code == HTTPStatus.OK
    assert 'access_token' in login.json()


def test_create_student_invalid_cpf(client, school_admin_token):
    resp = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'name': 'Carlos',
            'cpf': '11111111111',
            'birthdate': '2015-01-01',
            'turma_numero': 8,
            'turma_letra': 'B',
            'password': 'S3cr3t!123',
        },
    )

    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_create_student_duplicate_cpf(client, school_admin_token):
    payload = {
        'name': 'Ana',
        'cpf': '52998224725',
        'birthdate': '2015-01-01',
        'turma_numero': 7,
        'turma_letra': 'B',
        'password': 'S3cr3t!123',
    }
    first = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json=payload,
    )
    assert first.status_code == HTTPStatus.CREATED

    second = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={**payload, 'cpf': '52998224725'},
    )
    assert second.status_code == HTTPStatus.CONFLICT
    assert second.json() == {'detail': 'CPF already exists'}


def test_list_users_role_filter(client, user, student, token):
    resp = client.get(
        '/users/?role=student', headers={'Authorization': f'Bearer {token}'}
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] == 1
    assert resp.json()['items'][0]['role'] == 'student'


def test_list_users_school_filter_super_admin(
    client, session, school, other_school, super_admin_token
):
    import asyncio

    from src.models import User, UserRole
    from src.security import get_password_hash

    async def _add(school_id):
        u = User(
            username=f'filter_user_{school_id}',
            email=f'filter_user_{school_id}@ex.com',
            password=get_password_hash('secret'),
            role=UserRole.LIBRARIAN,
            school_id=school_id,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        session.expunge(u)

    asyncio.run(_add(school.id))
    asyncio.run(_add(other_school.id))

    resp = client.get(
        f'/users/?school_id={other_school.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    items = resp.json()['items']
    assert len(items) == 1
    assert items[0]['school_id'] == other_school.id


def test_list_users_school_filter_ignored_for_school_admin(
    client, session, school, other_school, school_admin_token
):
    import asyncio

    from src.models import User, UserRole
    from src.security import get_password_hash

    other = User(
        username='other_school_staff',
        email='other_school_staff@ex.com',
        password=get_password_hash('secret'),
        role=UserRole.LIBRARIAN,
        school_id=other_school.id,
    )
    session.add(other)
    asyncio.run(_commit_user(session))
    session.expunge(other)

    # school_admin tries to filter by other school but is restricted to own school
    resp = client.get(
        f'/users/?school_id={other_school.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    for item in resp.json()['items']:
        assert item['school_id'] == school.id


def test_update_student_turma_and_birthdate(
    client, student, school_admin, school_admin_token
):
    resp = client.put(
        f'/users/{student.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'turma_numero': 8, 'turma_letra': 'B', 'birthdate': '2014-03-20'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['turma_numero'] == 8
    assert resp.json()['turma_letra'] == 'B'
    assert resp.json()['birthdate'] == '2014-03-20'


async def _commit_user(session):
    await session.commit()
