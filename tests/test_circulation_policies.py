from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

import pytest

from src.circulation import resolve_circulation_policy
from src.models import (
    AdministrativeCapability,
    BooksStates,
    Loan,
    LoanStatus,
    UserAdministrativeCapability,
    UserRole,
)
from tests.factories import BookCopyFactory


def _policy_payload(*, student_loans=3, teacher_loans=5, can_reserve=True,
                    student_reservations=3, suspension_days=0):
    return {
        'policies': [
            {
                'reader_role': 'student',
                'max_active_loans': student_loans,
                'loan_duration_days': 14,
                'max_renewals': 0,
                'can_reserve': can_reserve,
                'max_active_reservations': student_reservations,
                'block_new_loans_when_overdue': True,
                'post_overdue_suspension_days': suspension_days,
            },
            {
                'reader_role': 'teacher',
                'max_active_loans': teacher_loans,
                'loan_duration_days': 21,
                'max_renewals': 0,
                'can_reserve': True,
                'max_active_reservations': 5,
                'block_new_loans_when_overdue': True,
                'post_overdue_suspension_days': 0,
            },
        ]
    }


@pytest.mark.asyncio
async def test_defaults_are_distinct_by_reader_role(session, school):
    student = await resolve_circulation_policy(
        session, school.id, UserRole.STUDENT
    )
    teacher = await resolve_circulation_policy(
        session, school.id, UserRole.TEACHER
    )

    assert (student.max_active_loans, student.loan_duration_days) == (3, 14)
    assert (teacher.max_active_loans, teacher.loan_duration_days) == (5, 21)


@pytest.mark.asyncio
async def test_school_admin_updates_only_own_school(
    session, client, school, other_school, school_admin, school_admin_token
):
    response = client.put(
        f'/circulation-policies/{school.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json=_policy_payload(student_loans=2),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['policies'][0]['max_active_loans'] == 2

    denied = client.get(
        f'/circulation-policies/{other_school.id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
    )
    assert denied.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_librarian_can_view_own_policies_but_needs_capability_to_update(
    session, client, user, token
):
    headers = {'Authorization': f'Bearer {token}'}
    assert client.get(
        f'/circulation-policies/{user.school_id}', headers=headers
    ).status_code == HTTPStatus.OK
    assert client.put(
        f'/circulation-policies/{user.school_id}',
        headers=headers,
        json=_policy_payload(),
    ).status_code == HTTPStatus.FORBIDDEN

    session.add(UserAdministrativeCapability(
        user_id=user.id,
        capability=AdministrativeCapability.MANAGE_CIRCULATION_RULES.value,
    ))
    await session.commit()
    assert client.put(
        f'/circulation-policies/{user.school_id}',
        headers=headers,
        json=_policy_payload(),
    ).status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_policy_limits_new_loans_and_uses_configured_duration(
    session, client, user, token, student, book, school_admin_token
):
    policy = _policy_payload(student_loans=1)
    policy['policies'][0]['loan_duration_days'] = 10
    updated = client.put(
        f'/circulation-policies/{user.school_id}',
        headers={'Authorization': f'Bearer {school_admin_token}'}, json=policy,
    )
    assert updated.status_code == HTTPStatus.OK

    copies = [
        BookCopyFactory(book_id=book.id, user_id=user.id, school_id=user.school_id),
        BookCopyFactory(book_id=book.id, user_id=user.id, school_id=user.school_id),
    ]
    session.add_all(copies)
    await session.commit()

    first = client.post(
        '/loans/', headers={'Authorization': f'Bearer {token}'},
        json={'copy_id': copies[0].id, 'user_id': student.id},
    )
    assert first.status_code == HTTPStatus.CREATED
    due = datetime.fromisoformat(first.json()['due_date'])
    assert due.date() == (datetime.now(tz=ZoneInfo('UTC')) + timedelta(days=10)).date()

    limited = client.post(
        '/loans/', headers={'Authorization': f'Bearer {token}'},
        json={'copy_id': copies[1].id, 'user_id': student.id},
    )
    assert limited.status_code == HTTPStatus.CONFLICT
    assert 'Limite de empréstimos' in limited.json()['detail']


@pytest.mark.asyncio
async def test_overdue_blocks_until_return_and_respects_suspension(
    session, client, user, token, student, book, school_admin_token
):
    policy = _policy_payload(suspension_days=2)
    assert client.put(
        f'/circulation-policies/{user.school_id}',
        headers={'Authorization': f'Bearer {school_admin_token}'}, json=policy,
    ).status_code == HTTPStatus.OK

    overdue_copy = BookCopyFactory(
        book_id=book.id, user_id=user.id, school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    available_copy = BookCopyFactory(
        book_id=book.id, user_id=user.id, school_id=user.school_id,
        state=BooksStates.AVAILABLE,
    )
    session.add_all([overdue_copy, available_copy])
    await session.flush()
    now = datetime.now(tz=ZoneInfo('UTC')).replace(tzinfo=None)
    overdue = Loan(
        copy_id=overdue_copy.id, user_id=student.id, school_id=user.school_id,
        due_date=now - timedelta(days=1), status=LoanStatus.ACTIVE,
    )
    session.add(overdue)
    await session.commit()

    blocked = client.post(
        '/loans/', headers={'Authorization': f'Bearer {token}'},
        json={'copy_id': available_copy.id, 'user_id': student.id},
    )
    assert blocked.status_code == HTTPStatus.CONFLICT
    assert 'empréstimo vencido' in blocked.json()['detail']

    overdue.status = LoanStatus.RETURNED
    overdue.returned_at = now
    overdue.late_days = 1
    overdue_copy.state = BooksStates.AVAILABLE
    session.add_all([overdue, overdue_copy])
    await session.commit()

    suspended = client.post(
        '/loans/', headers={'Authorization': f'Bearer {token}'},
        json={'copy_id': available_copy.id, 'user_id': student.id},
    )
    assert suspended.status_code == HTTPStatus.CONFLICT
    assert 'Empréstimos liberados em' in suspended.json()['detail']

    overdue.returned_at = now - timedelta(days=3)
    session.add(overdue)
    await session.commit()
    released = client.post(
        '/loans/', headers={'Authorization': f'Bearer {token}'},
        json={'copy_id': available_copy.id, 'user_id': student.id},
    )
    assert released.status_code == HTTPStatus.CREATED


@pytest.mark.asyncio
async def test_reservation_policy_can_disable_and_limit_reservations(
    session, client, user, student, student_token, book, school_admin_token
):
    assert client.put(
        f'/circulation-policies/{user.school_id}',
        headers={'Authorization': f'Bearer {school_admin_token}'},
        json=_policy_payload(can_reserve=False),
    ).status_code == HTTPStatus.OK
    copy = BookCopyFactory(
        book_id=book.id, user_id=user.id, school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    response = client.post(
        '/reservations/', headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert 'Reservas não são permitidas' in response.json()['detail']


@pytest.mark.asyncio
async def test_guest_cannot_resolve_personal_circulation_policy(session, school):
    with pytest.raises(Exception):
        await resolve_circulation_policy(session, school.id, 'guest')
