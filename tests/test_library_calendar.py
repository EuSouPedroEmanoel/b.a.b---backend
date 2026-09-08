from datetime import date
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select

from src.models import SchoolNonWorkingDay, User, UserRole
from src.routers import library_calendar
from src.security import get_password_hash


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_calendar_crud_and_permissions(
    client, school, user, token, school_admin_token
):
    base = f'/library-calendar/{school.id}'

    assert client.get(f'{base}?year=2026', headers=_auth(token)).status_code == 200
    denied = client.post(
        f'{base}/non-working-days',
        headers=_auth(token),
        json={'date': '2026-06-15'},
    )
    assert denied.status_code == 403

    created = client.post(
        f'{base}/non-working-days',
        headers=_auth(school_admin_token),
        json={'date': '2026-06-15'},
    )
    assert created.status_code == 201
    assert created.json() == {'date': '2026-06-15'}

    duplicate = client.post(
        f'{base}/non-working-days',
        headers=_auth(school_admin_token),
        json={'date': '2026-06-15'},
    )
    assert duplicate.status_code == 409

    calendar = client.get(f'{base}?year=2026', headers=_auth(token))
    assert calendar.json()['days'] == [{'date': '2026-06-15'}]

    missing = client.delete(
        f'{base}/non-working-days/2026-06-16',
        headers=_auth(school_admin_token),
    )
    assert missing.status_code == 404

    deleted = client.delete(
        f'{base}/non-working-days/2026-06-15',
        headers=_auth(school_admin_token),
    )
    assert deleted.status_code == 204


def test_calendar_range_skips_weekends_and_existing_days(
    client, school, school_admin_token, session
):
    session.add(SchoolNonWorkingDay(school_id=school.id, date=date(2026, 6, 9)))
    import asyncio

    asyncio.run(session.commit())
    response = client.post(
        f'/library-calendar/{school.id}/non-working-days/range',
        headers=_auth(school_admin_token),
        json={'start_date': '2026-06-05', 'end_date': '2026-06-09'},
    )
    assert response.status_code == 201
    assert [item['date'] for item in response.json()] == [
        '2026-06-05', '2026-06-08'
    ]


def test_calendar_month_create_and_delete(client, school, school_admin_token):
    base = f'/library-calendar/{school.id}'
    created = client.post(
        f'{base}/non-working-days/month',
        headers=_auth(school_admin_token),
        json={'year': 2026, 'month': 2},
    )
    assert created.status_code == 201
    assert len(created.json()) == 20

    repeated = client.post(
        f'{base}/non-working-days/month',
        headers=_auth(school_admin_token),
        json={'year': 2026, 'month': 2},
    )
    assert repeated.status_code == 201
    assert repeated.json() == []

    invalid = client.delete(
        f'{base}/non-working-days/month/2026/13',
        headers=_auth(school_admin_token),
    )
    assert invalid.status_code == 400

    deleted = client.delete(
        f'{base}/non-working-days/month/2026/2',
        headers=_auth(school_admin_token),
    )
    assert deleted.status_code == 204
    assert client.get(f'{base}?year=2026', headers=_auth(school_admin_token)).json()['days'] == []


def test_calendar_national_holiday_preview_and_import(
    client, school, school_admin_token, session, monkeypatch
):
    async def fake_holidays(year):
        assert year == 2026
        return [
            {'date': date(2026, 1, 1), 'name': 'Confraternização Universal'},
            {'date': date(2026, 4, 21), 'name': 'Tiradentes'},
        ]

    monkeypatch.setattr(
        'src.routers.library_calendar._fetch_national_holidays', fake_holidays
    )
    session.add(SchoolNonWorkingDay(school_id=school.id, date=date(2026, 1, 1)))
    import asyncio

    asyncio.run(session.commit())

    base = f'/library-calendar/{school.id}/national-holidays'
    preview = client.get(f'{base}?year=2026', headers=_auth(school_admin_token))
    assert preview.status_code == 200
    assert preview.json()['already_added_count'] == 1
    assert preview.json()['added_count'] == 1
    assert preview.json()['holidays'] == [
        {
            'date': '2026-01-01',
            'name': 'Confraternização Universal',
            'already_added': True,
        },
        {
            'date': '2026-04-21',
            'name': 'Tiradentes',
            'already_added': False,
        },
    ]

    imported = client.post(
        f'{base}/import?year=2026', headers=_auth(school_admin_token)
    )
    assert imported.status_code == 200
    assert imported.json()['already_added_count'] == 2
    assert imported.json()['added_count'] == 0


def test_calendar_missing_school_and_invalid_range(client, school_admin_token):
    headers = _auth(school_admin_token)
    assert client.get('/library-calendar/99999?year=2026', headers=headers).status_code == 404


def test_calendar_rejects_inverted_range(client, school, school_admin_token):
    headers = _auth(school_admin_token)
    invalid = client.post(
        f'/library-calendar/{school.id}/non-working-days/range',
        headers=headers,
        json={'start_date': '2026-06-10', 'end_date': '2026-06-01'},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_school_admin_cannot_delete_other_school_calendar_day(
    client, session, school, other_school
):
    protected_day = date(2026, 6, 15)
    session.add(
        SchoolNonWorkingDay(school_id=school.id, date=protected_day)
    )
    other_admin = User(
        username='calendar_other_school_admin',
        name='Calendar Other School Admin',
        email='calendar_other_school_admin@example.com',
        password=get_password_hash('other-school-password'),
        role=UserRole.SCHOOL_ADMIN,
        school_id=other_school.id,
    )
    session.add(other_admin)
    await session.commit()

    own_token = client.post(
        '/auth/token',
        data={
            'username': other_admin.username,
            'password': 'other-school-password',
        },
    )
    assert own_token.status_code == 200

    denied = client.delete(
        f'/library-calendar/{school.id}/non-working-days/{protected_day}',
        headers=_auth(own_token.json()['access_token']),
    )
    assert denied.status_code == 403

    persisted_day = await session.scalar(
        select(SchoolNonWorkingDay).where(
            SchoolNonWorkingDay.school_id == school.id,
            SchoolNonWorkingDay.date == protected_day,
        )
    )
    assert persisted_day is not None


@pytest.mark.asyncio
async def test_fetch_national_holidays_filters_invalid_entries(monkeypatch):
    response = MagicMock()
    response.json.return_value = [
        {'date': '2026-01-01', 'name': 'Ano Novo', 'type': 'national'},
        {'date': '2026-02-01', 'name': 'Municipal', 'type': 'municipal'},
        {'date': 'invalid', 'name': 'Inválido'},
        {'name': 'Sem data'},
        'not-an-object',
    ]
    client = AsyncMock()
    client.get.return_value = response

    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr('src.routers.library_calendar.httpx.AsyncClient', AsyncClient)
    result = await library_calendar._fetch_national_holidays(2026)
    assert result == [{'date': date(2026, 1, 1), 'name': 'Ano Novo'}]
    response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_national_holidays_rejects_invalid_year():
    with pytest.raises(Exception) as error:
        await library_calendar._fetch_national_holidays(1899)
    assert error.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http', 'json', 'payload'])
async def test_fetch_national_holidays_external_failures(monkeypatch, failure):
    response = MagicMock()
    response.raise_for_status.side_effect = (
        httpx.HTTPError('offline') if failure == 'http' else None
    )
    if failure == 'json':
        response.json.side_effect = ValueError('invalid json')
    elif failure == 'payload':
        response.json.return_value = {'unexpected': True}
    client = AsyncMock()
    client.get.return_value = response

    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr('src.routers.library_calendar.httpx.AsyncClient', AsyncClient)
    with pytest.raises(Exception) as error:
        await library_calendar._fetch_national_holidays(2026)
    assert error.value.status_code == 502
