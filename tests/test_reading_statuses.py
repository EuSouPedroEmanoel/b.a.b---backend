from datetime import datetime, timedelta
from http import HTTPStatus

import pytest

from src.models import BookCopy, Loan, ReadingStatus, UserReadingStatus
from tests.factories import BookCopyFactory


def _auth(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_student_can_create_update_read_and_remove_status(
    client, student, student_token, user, book, school, session
):
    session.add(
        BookCopyFactory(
            book_id=book.id, school_id=school.id, added_by=user.id
        )
    )
    await session.commit()

    headers = _auth(student_token)
    path = f'/books/{book.id}/reading-status'

    empty = client.get(path, headers=headers)
    assert empty.status_code == HTTPStatus.OK
    assert empty.json()['book_id'] == book.id
    assert empty.json()['status'] is None

    created = client.put(
        path,
        headers=headers,
        json={'status': ReadingStatus.WANT_TO_READ.value},
    )
    assert created.status_code == HTTPStatus.OK
    assert created.json()['status'] == ReadingStatus.WANT_TO_READ.value

    updated = client.put(
        path,
        headers=headers,
        json={'status': ReadingStatus.READ.value},
    )
    assert updated.status_code == HTTPStatus.OK
    assert updated.json()['status'] == ReadingStatus.READ.value
    assert await session.scalar(
        __import__('sqlalchemy').select(UserReadingStatus).where(
            UserReadingStatus.user_id == student.id,
            UserReadingStatus.book_id == book.id,
        )
    ) is not None

    listed = client.get(
        f'/reading-statuses/me?status={ReadingStatus.READ.value}',
        headers=headers,
    )
    assert listed.status_code == HTTPStatus.OK
    assert [item['id'] for item in listed.json()['items']] == [book.id]
    assert listed.json()['items'][0]['reading_status'] == ReadingStatus.READ.value

    borrowed_copy = BookCopyFactory(
        book_id=book.id, school_id=school.id, added_by=user.id
    )
    session.add(borrowed_copy)
    await session.flush()
    session.add(
        Loan(
            copy_id=borrowed_copy.id,
            user_id=student.id,
            school_id=school.id,
            due_date=datetime.now() + timedelta(days=7),
        )
    )
    await session.commit()
    borrowed = client.get(
        '/reading-statuses/me?borrowed_only=true', headers=headers
    )
    assert borrowed.status_code == HTTPStatus.OK
    assert [item['id'] for item in borrowed.json()['items']] == [book.id]

    removed = client.delete(path, headers=headers)
    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert client.get(path, headers=headers).json()['status'] is None


def test_invalid_status_and_non_student_are_rejected(
    client, token, book
):
    path = f'/books/{book.id}/reading-status'
    invalid = client.put(path, headers=_auth(token), json={'status': 'invalid'})
    assert invalid.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_guest_and_other_school_cannot_manage_status(
    client, school, other_school, student, student_token, user, book, session
):
    session.add(
        BookCopy(
            code='OTHER-SCHOOL-COPY',
            book_id=book.id,
            added_by=user.id,
            school_id=other_school.id,
        )
    )
    await session.commit()

    guest_token = client.post(
        '/auth/guest', json={'school_code': school.code}
    ).json()['access_token']
    path = f'/books/{book.id}/reading-status'
    guest = client.get(path, headers=_auth(guest_token))
    assert guest.status_code == HTTPStatus.FORBIDDEN

    hidden = client.get(path, headers=_auth(student_token))
    assert hidden.status_code == HTTPStatus.NOT_FOUND
