from http import HTTPStatus

import pytest
from sqlalchemy import select

from scr.models import School


def test_create_school_success(client, super_admin_token):
    resp = client.post(
        '/schools/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Escola Teste', 'code': 'SCH-NEW-001'},
    )
    assert resp.status_code == HTTPStatus.CREATED
    data = resp.json()
    assert data['name'] == 'Escola Teste'
    assert data['code'] == 'SCH-NEW-001'
    assert data['is_active'] is True
    assert 'id' in data


def test_create_school_conflict(client, super_admin_token, school):
    resp = client.post(
        '/schools/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Outra', 'code': school.code},
    )
    assert resp.status_code == HTTPStatus.CONFLICT
    assert resp.json()['detail'] == 'School code already exists'


def test_create_school_forbidden(client, token):
    resp = client.post(
        '/schools/',
        headers={'Authorization': f'Bearer {token}'},
        json={'name': 'Escola X', 'code': 'SCH-X'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


def test_list_schools_success(client, super_admin_token, school):
    resp = client.get(
        '/schools/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert 'schools' in resp.json()
    assert len(resp.json()['schools']) >= 1


def test_list_schools_pagination(client, super_admin_token, school):
    resp = client.get(
        '/schools/?limit=1&offset=0',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert len(resp.json()['schools']) == 1


def test_list_schools_forbidden(client, token):
    resp = client.get(
        '/schools/',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


def test_get_school_success(client, super_admin_token, school):
    resp = client.get(
        f'/schools/{school.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['code'] == school.code


def test_get_school_not_found(client, super_admin_token):
    resp = client.get(
        '/schools/9999',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_create_school_admin_success(client, super_admin_token, school):
    resp = client.post(
        f'/schools/{school.id}/admins',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'admin_test_school',
            'email': 'admin_test@escola.com',
            'password': 'secret123',
        },
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert resp.json()['username'] == 'admin_test_school'
    assert resp.json()['school_id'] == school.id
    assert resp.json()['role'] == 'school_admin'


def test_create_school_admin_not_found(client, super_admin_token):
    resp = client.post(
        '/schools/9999/admins',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'x',
            'email': 'x@ex.com',
            'password': 'secret123',
        },
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_create_school_admin_inactive(
    session, client, super_admin_token, school
):
    db_school = await session.get(School, school.id)
    db_school.is_active = False
    await session.commit()

    resp = client.post(
        f'/schools/{school.id}/admins',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': 'admin2',
            'email': 'admin2@ex.com',
            'password': 'secret123',
        },
    )
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert resp.json()['detail'] == 'School is inactive'


def test_create_school_admin_conflict(
    client, super_admin_token, school, user
):
    # user already exists with username/email
    resp = client.post(
        f'/schools/{school.id}/admins',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={
            'username': user.username,
            'email': 'newemail@ex.com',
            'password': 'secret123',
        },
    )
    assert resp.status_code == HTTPStatus.CONFLICT


def test_delete_school_success(client, super_admin_token, school):
    resp = client.delete(
        f'/schools/{school.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['message'] == 'School deleted'

    # confirm gone
    get = client.get(
        f'/schools/{school.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert get.status_code == HTTPStatus.NOT_FOUND


def test_delete_school_not_found(client, super_admin_token):
    resp = client.delete(
        '/schools/9999',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_delete_school_forbidden(client, token, school):
    resp = client.delete(
        f'/schools/{school.id}',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_school_model_relationship(session, school, user):
    # cover School.users relationship via select
    db_school = await session.scalar(
        select(School).where(School.id == school.id)
    )
    assert db_school is not None
    assert len(db_school.users) >= 1
