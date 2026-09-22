from http import HTTPStatus

import pytest

from src.models import AdministrativeActivity


def _headers(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_school_admin_sees_only_own_school_activity(
    client, session, school_admin, school_admin_token, other_school
):
    session.add_all([
        AdministrativeActivity(
            id='activity-own',
            actor_id=school_admin.id,
            actor_display_name='Admin Escola',
            actor_role='school_admin',
            school_id=school_admin.school_id,
            operation='updated',
            entity_type='school',
            entity_id=str(school_admin.school_id),
            summary='Preferência alterada.',
        ),
        AdministrativeActivity(
            id='activity-other',
            actor_id=None,
            actor_display_name='Conta removida',
            actor_role='school_admin',
            school_id=other_school.id,
            operation='updated',
            entity_type='school',
            entity_id=str(other_school.id),
            summary='Não deve aparecer.',
        ),
    ])
    await session.commit()

    response = client.get(
        '/administrative-activities/?size=1&school_id=9999',
        headers=_headers(school_admin_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['id'] == 'activity-own'


@pytest.mark.asyncio
async def test_super_admin_can_filter_activity_by_school(
    client, session, super_admin, super_admin_token, school, other_school
):
    session.add_all([
        AdministrativeActivity(
            id='activity-school-a',
            actor_id=super_admin.id,
            actor_display_name='Super Admin',
            actor_role='super_admin',
            school_id=school.id,
            operation='created',
            entity_type='user',
            entity_id='10',
            summary='Usuário criado.',
        ),
        AdministrativeActivity(
            id='activity-school-b',
            actor_id=super_admin.id,
            actor_display_name='Super Admin',
            actor_role='super_admin',
            school_id=other_school.id,
            operation='created',
            entity_type='user',
            entity_id='11',
            summary='Outro usuário criado.',
        ),
    ])
    await session.commit()

    response = client.get(
        f'/administrative-activities/?school_id={other_school.id}',
        headers=_headers(super_admin_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert [item['id'] for item in response.json()['items']] == [
        'activity-school-b'
    ]


def test_non_administrator_cannot_read_activity(client, token):
    response = client.get(
        '/administrative-activities/', headers=_headers(token)
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_activity_filter_validation_and_missing_authentication(client):
    invalid = client.get('/administrative-activities/?page=0')
    assert invalid.status_code == HTTPStatus.UNAUTHORIZED
