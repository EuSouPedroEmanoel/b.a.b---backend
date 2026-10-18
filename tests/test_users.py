from http import HTTPStatus

import pytest
from fastapi import HTTPException

from src.models import AccountStatus, User, UserRole
from src.routers import users as users_router
from src.schemas import UserPublic
from src.security import get_password_hash
from src.utils.cpf import cpf_storage_values


def test_create_user(client, school, super_admin_token):
    response = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'alice',
            'name': 'Alice Biblioteca',
            'email': 'alice@exemple.com',
            'cpf': '11144477735',
            'password': 'S3cr3t!123',
            'role': 'librarian',
            'school_id': school.id,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['username'] == 'alice'
    assert response.json()['name'] == 'Alice Biblioteca'
    assert response.json()['school_id'] == school.id
    assert response.json()['cpf_masked'] == '•••.•••.•••-35'
    assert 'cpf' not in response.json()
    assert 'cpf_lookup_hash' not in response.json()
    assert 'cpf_collision_guard' not in response.json()


def test_deactivate_user_revokes_existing_session_and_can_be_undone(
    client, token, other_user
):
    previous_token = client.post(
        '/auth/token',
        data={
            'username': other_user.username,
            'password': other_user.clean_password,
        },
    ).json()['access_token']
    response = client.post(
        f'/users/{other_user.id}/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': False, 'justification': 'Afastamento administrativo.'},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['is_active'] is False
    assert client.get(
        '/users/me', headers={'Authorization': f'Bearer {previous_token}'}
    ).status_code == HTTPStatus.FORBIDDEN
    response = client.post(
        f'/users/{other_user.id}/situation/undo',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['is_active'] is True


@pytest.mark.asyncio
async def test_reactivation_preserves_pending_activation_status(
    session, client, token, school
):
    pending = User(
        username='pending-lifecycle',
        name='Pending Lifecycle',
        password=None,
        role=UserRole.STUDENT,
        school_id=school.id,
        account_status=AccountStatus.PENDING_ACTIVATION,
        is_active=True,
    )
    session.add(pending)
    await session.commit()
    deactivate = client.post(
        f'/users/{pending.id}/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': False, 'justification': 'Conta não iniciada.'},
    )
    assert deactivate.status_code == HTTPStatus.OK
    assert deactivate.json()['account_status'] == 'disabled'
    reactivate = client.post(
        f'/users/{pending.id}/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': True},
    )
    assert reactivate.status_code == HTTPStatus.OK
    assert reactivate.json()['is_active'] is True
    assert reactivate.json()['account_status'] == 'pending_activation'
    history = client.get(
        f'/users/{pending.id}/situation-audit',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert history.status_code == HTTPStatus.OK
    assert history.json()[0]['previous_account_status'] == 'pending_activation'


def test_simulated_lookup_collision_allows_second_student(
    client, school_admin_token, monkeypatch, caplog
):
    import src.routers.users as users_router
    from src.utils.cpf import cpf_storage_values

    first_cpf = '52998224725'
    second_cpf = '39053344705'
    first_values = cpf_storage_values(first_cpf)
    second_values = cpf_storage_values(second_cpf)

    def simulated_values(cpf):
        if cpf == second_cpf:
            return first_values[0], second_values[1], second_values[2]
        return first_values

    monkeypatch.setattr(users_router, 'cpf_storage_values', simulated_values)
    monkeypatch.setattr(
        users_router,
        'cpf_lookup_digest',
        lambda cpf: first_values[0]
        if cpf == second_cpf
        else cpf_storage_values(cpf)[0],
    )
    monkeypatch.setattr(
        users_router,
        'cpf_collision_guard',
        lambda cpf: second_values[1]
        if cpf == second_cpf
        else cpf_storage_values(cpf)[1],
    )
    payload = {
        'name': 'Primeiro aluno',
        'cpf': first_cpf,
        'birthdate': '2015-05-10',
        'turma_numero': 7,
        'turma_letra': 'A',
    }
    first = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json=payload,
    )
    second = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={**payload, 'name': 'Segundo aluno', 'cpf': second_cpf},
    )

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED
    lookup = client.get(
        f'/users/?cpf={second_cpf}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert lookup.status_code == HTTPStatus.OK
    assert lookup.json()['items'][0]['id'] == second.json()['id']
    collision_records = [
        record for record in caplog.records
        if record.getMessage() == 'CPF_LOOKUP_HASH_COLLISION'
    ]
    assert collision_records
    event_text = collision_records[-1].getMessage()
    assert first_cpf not in event_text
    assert second_cpf not in event_text
    assert first_values[0].hex() not in str(collision_records[-1].__dict__)
    assert second_values[1].hex() not in str(collision_records[-1].__dict__)


def test_create_user_integraty(client, school, super_admin_token):
    client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'cpf': '52998224725',
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
            'cpf': '12345678909',
            'password': 'newsecret',
            'role': 'librarian',
            'school_id': school.id,
        },
    )

    assert actual_update.status_code == HTTPStatus.CONFLICT
    assert actual_update.json() == {
        'detail': 'Username, Email or CPF already exists!!'
    }


def test_read_users(client, user, school_admin_token):

    user_schema = UserPublic.model_validate(user).model_dump(mode='json')
    response = client.get(
        '/users/', headers={'Authorization': f'Bearer {school_admin_token}'}
    )
    assert response.status_code == HTTPStatus.OK
    assert user_schema in response.json()['items']
    assert response.json()['total'] == 2


def test_read_user_by_id(client, user, school_admin_token):
    response = client.get(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == UserPublic.model_validate(user).model_dump(
        mode='json'
    )


def test_read_users_is_forbidden_for_student_and_teacher(
    client, user, token, student, student_token, teacher, teacher_token
):
    for access_token in (token, student_token, teacher_token):
        response = client.get(
            '/users/', headers={'Authorization': f'Bearer {access_token}'}
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {'detail': 'Not enough permissions'}


def test_read_user_by_id_is_forbidden_for_student_and_teacher(
    client, user, token, student, student_token, teacher, teacher_token
):
    for user_id, access_token in (
        (user.id, token),
        (student.id, student_token),
        (teacher.id, teacher_token),
    ):
        response = client.get(
            f'/users/{user_id}',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {'detail': 'Not enough permissions'}


def test_read_current_user_uses_authenticated_identity(
    client, student, student_token, teacher
):
    response = client.get(
        f'/users/me?user_id={teacher.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['id'] == student.id
    assert data['username'] == student.username
    assert 'cpf_masked' not in data
    assert 'birthdate' not in data
    assert 'turma_numero' not in data
    assert 'turma_letra' not in data


def test_read_current_user_rejects_invalid_and_missing_tokens(client):
    invalid = client.get(
        '/users/me', headers={'Authorization': 'Bearer invalid.token'}
    )
    missing = client.get('/users/me')

    assert invalid.status_code == HTTPStatus.UNAUTHORIZED
    assert invalid.json() == {'detail': 'Could not validate credentials'}
    assert missing.status_code == HTTPStatus.UNAUTHORIZED
    assert missing.json() == {'detail': 'Not authenticated'}


def test_terms_acceptance_is_versioned_and_persisted(
    client, student, student_token
):
    before = client.get(
        '/users/me', headers={'Authorization': f'Bearer {student_token}'}
    )
    assert before.status_code == HTTPStatus.OK
    assert before.json()['terms_accepted_version'] is None
    assert before.json()['terms_current_version'] == 'v1'

    accepted = client.post(
        '/users/me/terms-acceptance',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert accepted.status_code == HTTPStatus.OK
    assert accepted.json()['terms_accepted_version'] == 'v1'
    assert accepted.json()['terms_accepted_at'] is not None

    repeated = client.post(
        '/users/me/terms-acceptance',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert repeated.status_code == HTTPStatus.OK
    assert repeated.json()['terms_accepted_version'] == 'v1'


def test_cannot_change_own_account_situation(client, user, token):
    deactivation = client.post(
        f'/users/{user.id}/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': False, 'justification': 'Encerramento da conta.'},
    )
    assert deactivation.status_code == HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_read_users_filters_by_cpf_excludes_inactive_user(
    session, client, school, school_admin_token
):
    inactive = User(
        username='inactive_lookup',
        cpf_lookup_hash=cpf_storage_values('52998224725')[0],
        cpf_collision_guard=cpf_storage_values('52998224725')[1],
        cpf_last2='25',
        password=get_password_hash('secret'),
        role=UserRole.STUDENT,
        school_id=school.id,
        is_active=False,
    )
    session.add(inactive)
    await session.commit()

    response = client.get(
        '/users/?cpf=529.982.247-25',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 0
    assert response.json()['items'] == []


@pytest.mark.asyncio
async def test_read_users_filters_by_cpf_returns_active_user(
    session, client, school, school_admin_token
):
    active = User(
        username='active_lookup',
        cpf_lookup_hash=cpf_storage_values('39053344705')[0],
        cpf_collision_guard=cpf_storage_values('39053344705')[1],
        cpf_last2='05',
        password=get_password_hash('secret'),
        role=UserRole.STUDENT,
        school_id=school.id,
        is_active=True,
    )
    session.add(active)
    await session.commit()

    response = client.get(
        '/users/?cpf=390.533.447-05',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['id'] == active.id
    assert response.json()['items'][0]['is_active'] is True


def test_raise_read_user_by_id(client, user, school_admin_token):
    response = client.get(
        '/users/9999',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'User Not Found...'}


def test_update_user(client, user, token):
    response = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'username': 'Pedro',
            'name': 'Pedro Silva',
            'email': 'pedro@email.ai',
            'password': 'secret',
        },
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data['username'] == 'Pedro'
    assert data['name'] == 'Pedro Silva'
    assert data['id'] == user.id
    assert data['role'] == user.role
    assert data['school_id'] == user.school_id


def test_super_admin_updates_school_admin(
    client, school_admin, super_admin_token
):
    response = client.put(
        f'/users/{school_admin.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'name': 'Admin Atualizado',
            'email': 'school-admin-updated@example.com',
            'password': 'new-secret',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['name'] == 'Admin Atualizado'
    assert response.json()['role'] == UserRole.SCHOOL_ADMIN


def test_super_admin_cannot_update_non_school_admin(
    client, user, super_admin_token
):
    response = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'email': 'librarian-updated@example.com'},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json() == {'detail': 'Not enough permissions'}


def test_update_integrity_error(
    client, user, token, school, super_admin_token
):
    client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'fausto',
            'email': 'fausto@exemple.lol',
            'cpf': '98765432100',
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
        'detail': 'Username, Email or CPF already exists!!'
    }


def test_delete_user(client, user, token):
    response = client.delete(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_raise_delete_user_forbidden(client, other_user, token):
    response = client.delete(
        f'/users/{other_user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


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
            'cpf': '11144477735',
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
            'cpf': '12345678909',
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
            'cpf': '52998224725',
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
    client, user, school_admin_token, other_school, session
):
    from src.models import User, UserRole
    from src.security import get_password_hash

    other_user = User(
        username='cross_school_user',
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
        f'/users/{other_user.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'}
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_school_admin_reads_user_from_own_school(
    client, user, school_admin_token
):
    response = client.get(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['id'] == user.id


def test_school_admin_cannot_read_user_from_another_school(
    client, other_school, school_admin_token, super_admin_token
):
    created = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'other_school_reader',
            'name': 'Leitor de outra escola',
            'email': 'other-school-reader@example.com',
            'cpf': '52998224725',
            'password': 'S3cr3t!123',
            'role': 'librarian',
            'school_id': other_school.id,
        },
    )
    assert created.status_code == HTTPStatus.CREATED

    response = client.get(
        f"/users/{created.json()['id']}",
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'User Not Found...'}


def test_super_admin_reads_user_from_another_school(
    client, other_school, super_admin_token
):
    created = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'super_admin_cross_school_target',
            'name': 'Leitor entre escolas',
            'email': 'super-admin-cross-school@example.com',
            'cpf': '11144477735',
            'password': 'S3cr3t!123',
            'role': 'librarian',
            'school_id': other_school.id,
        },
    )
    assert created.status_code == HTTPStatus.CREATED

    response = client.get(
        f"/users/{created.json()['id']}",
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['school_id'] == other_school.id


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
    assert data['name'] == 'João da Silva'
    assert data['cpf_masked'] == '•••.•••.•••-25'
    assert 'cpf' not in data
    assert data['birthdate'] == '2015-05-10'
    assert data['turma_numero'] == 7
    assert data['turma_letra'] == 'A'
    assert data['school_id'] == school_admin.school_id


def test_create_student_requires_first_access_activation(
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
    assert resp.json()['name'] == 'Maria'
    created = resp.json()
    username = created['username']

    login = client.post(
        '/auth/token',
        data={'username': username, 'password': '10052015'},
    )
    assert login.status_code == HTTPStatus.FORBIDDEN

    activation = client.post(
        '/account-activation/complete',
        json={
            'username': username,
            'code': created['activation_invitation']['code'],
            'password': 'NovaSenha123',
            'password_confirmation': 'NovaSenha123',
        },
    )
    assert activation.status_code == HTTPStatus.OK

    login = client.post(
        '/auth/token',
        data={'username': username, 'password': 'NovaSenha123'},
    )
    assert login.status_code == HTTPStatus.OK


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


def test_create_user_rejects_invalid_student_turma_letter(
    client, school, super_admin_token
):
    response = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'name': 'Turma inválida',
            'cpf': '39053344705',
            'birthdate': '2015-01-01',
            'turma_numero': 7,
            'turma_letra': '1',
            'role': 'student',
            'school_id': school.id,
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_create_staff_rejects_username_longer_than_activation_contract(
    client, school, super_admin_token
):
    response = client.post(
        '/users/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'u' * 121,
            'name': 'Usuário longo',
            'cpf': '39053344705',
            'role': 'teacher',
            'school_id': school.id,
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


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


def test_list_users_role_filter(client, user, student, school_admin_token):
    resp = client.get(
        '/users/?role=student',
        headers={'Authorization': f'Bearer {school_admin_token}'}
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
        json={
            'turma_numero': 8,
            'turma_letra': 'B',
            'birthdate': '2014-03-20',
        },
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['turma_numero'] == 8
    assert resp.json()['turma_letra'] == 'B'
    assert resp.json()['birthdate'] == '2014-03-20'


def test_update_administrative_capabilities(
    client, user, school_admin_token, token
):
    response = client.put(
        f'/users/{user.id}/administrative-capabilities',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'manage_library_calendar': True,
            'manage_circulation_rules': False,
        },
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['user_id'] == user.id
    assert response.json()['capabilities'] == ['manage_library_calendar']

    forbidden = client.put(
        f'/users/{user.id}/administrative-capabilities',
        headers={'Authorization': f'Bearer {token}'},
        json={'manage_library_calendar': False},
    )
    assert forbidden.status_code == HTTPStatus.FORBIDDEN

    replaced = client.put(
        f'/users/{user.id}/administrative-capabilities',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'manage_library_calendar': False,
            'manage_circulation_rules': True,
        },
    )
    assert replaced.json()['capabilities'] == ['manage_circulation_rules']


def test_update_administrative_capabilities_rejects_non_librarian(
    client, student, school_admin_token
):
    response = client.put(
        f'/users/{student.id}/administrative-capabilities',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'manage_library_calendar': True},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_password_reset_can_be_undone(client, user, school_admin_token):
    reset = client.post(
        f'/users/{user.id}/password/reset',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert reset.status_code == HTTPStatus.OK
    data = reset.json()
    assert data['undo_id'] is not None
    assert data['code']

    undone = client.post(
        f'/users/{user.id}/password/reset/undo',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'undo_id': data['undo_id']},
    )
    assert undone.status_code == HTTPStatus.OK
    assert undone.json() == {'message': 'Reset de senha desfeito.'}


def test_password_reset_undo_requires_valid_undo_id(client, user, token):
    missing = client.post(
        f'/users/{user.id}/password/reset/undo',
        headers={'Authorization': f'Bearer {token}'},
        json={},
    )
    assert missing.status_code == HTTPStatus.BAD_REQUEST

    invalid = client.post(
        f'/users/{user.id}/password/reset/undo',
        headers={'Authorization': f'Bearer {token}'},
        json={'undo_id': 99999},
    )
    assert invalid.status_code == HTTPStatus.CONFLICT


def test_activation_state_regeneration_and_invalid_print(client, user, token):
    state = client.get(
        f'/users/{user.id}/activation',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert state.status_code == HTTPStatus.OK
    assert state.json()['has_active_invitation'] is False

    regeneration = client.post(
        f'/users/{user.id}/activation/regenerate',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert regeneration.status_code == HTTPStatus.CONFLICT

    printed = client.post(
        f'/users/{user.id}/activation/print',
        headers={'Authorization': f'Bearer {token}'},
        json={'username': user.username, 'code': 'BAD-CODE'},
    )
    assert printed.status_code == HTTPStatus.BAD_REQUEST


def test_user_lifecycle_missing_targets_and_repeated_state(
    client, user, token, other_user
):
    missing_activation = client.get(
        '/users/99999/activation',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert missing_activation.status_code == HTTPStatus.NOT_FOUND

    missing_situation = client.post(
        '/users/99999/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': False, 'justification': 'Teste'},
    )
    assert missing_situation.status_code == HTTPStatus.NOT_FOUND

    repeated = client.post(
        f'/users/{other_user.id}/situation',
        headers={'Authorization': f'Bearer {token}'},
        json={'is_active': True, 'justification': 'Teste'},
    )
    assert repeated.status_code == HTTPStatus.CONFLICT

    undo_without_audit = client.post(
        f'/users/{other_user.id}/situation/undo',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert undo_without_audit.status_code == HTTPStatus.CONFLICT


def test_password_reset_cannot_be_undone_after_new_invitation(
    client, user, school_admin_token
):
    first = client.post(
        f'/users/{user.id}/password/reset',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert first.status_code == HTTPStatus.OK
    second = client.post(
        f'/users/{user.id}/password/reset',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert second.status_code == HTTPStatus.OK

    response = client.post(
        f'/users/{user.id}/password/reset/undo',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'undo_id': first.json()['undo_id']},
    )
    assert response.status_code == HTTPStatus.CONFLICT


def test_latest_password_reset_undo_restores_previous_invitation(
    client, user, school_admin_token
):
    first = client.post(
        f'/users/{user.id}/password/reset',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    second = client.post(
        f'/users/{user.id}/password/reset',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert first.status_code == second.status_code == HTTPStatus.OK

    response = client.post(
        f'/users/{user.id}/password/reset/undo',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'undo_id': second.json()['undo_id']},
    )
    assert response.status_code == HTTPStatus.OK


def test_cannot_deactivate_last_school_admin(
    client, school_admin, super_admin_token
):
    response = client.post(
        f'/users/{school_admin.id}/situation',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'is_active': False, 'justification': 'Teste'},
    )
    assert response.status_code == HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_cannot_deactivate_last_super_admin(
    session, super_admin
):
    with pytest.raises(HTTPException) as error:
        await users_router._ensure_not_last_administrator(session, super_admin)
    assert error.value.status_code == HTTPStatus.CONFLICT


def test_update_user_validation_and_missing_target(client, user, token):
    empty = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={},
    )
    assert empty.status_code == HTTPStatus.BAD_REQUEST

    invalid_cpf = client.put(
        f'/users/{user.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={'cpf': '11111111111'},
    )
    assert invalid_cpf.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    missing = client.put(
        '/users/99999',
        headers={'Authorization': f'Bearer {token}'},
        json={'name': 'Não existe'},
    )
    assert missing.status_code == HTTPStatus.NOT_FOUND


def test_update_user_cpf_and_student_fields(
    client, student, school_admin_token
):
    created = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'name': 'Outro aluno',
            'cpf': '11144477735',
            'birthdate': '2014-02-01',
            'turma_numero': 8,
            'turma_letra': 'B',
        },
    )
    assert created.status_code == HTTPStatus.CREATED
    duplicate = client.put(
        f'/users/{student.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={'cpf': '11144477735'},
    )
    assert duplicate.status_code == HTTPStatus.CONFLICT

    response = client.put(
        f'/users/{student.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json={
            'cpf': '39053344705',
            'name': 'Aluno Atualizado',
            'birthdate': '2013-02-01',
            'turma_numero': 9,
            'turma_letra': 'C',
        },
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['name'] == 'Aluno Atualizado'
    assert response.json()['cpf_masked'].endswith('-05')


def test_create_student_super_admin_without_school_is_rejected(
    client, super_admin_token
):
    response = client.post(
        '/users/students',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'name': 'Sem escola',
            'cpf': '39053344705',
            'birthdate': '2015-01-01',
            'turma_numero': 1,
            'turma_letra': 'A',
        },
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_student_username_is_made_unique(
    client, school_admin_token
):
    payload = {
        'name': 'Aluno Repetido',
        'cpf': '39053344705',
        'birthdate': '2015-01-01',
        'turma_numero': 1,
        'turma_letra': 'A',
    }
    first = client.post(
        '/users/students', headers={'Authorization': f'Bearer {school_admin_token}'},
        json=payload,
    )
    second = client.post(
        '/users/students', headers={'Authorization': f'Bearer {school_admin_token}'},
        json={**payload, 'cpf': '52998224725'},
    )
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED
    assert second.json()['username'] == f"{first.json()['username']}.1"


async def _commit_user(session):
    await session.commit()
