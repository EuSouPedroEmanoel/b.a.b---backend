from datetime import datetime, timezone
from http import HTTPStatus

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models import (
    Book,
    BooksStates,
    Loan,
    UserBookFavorite,
    UserRole,
)
from src.routers import favorites as favorites_router
from tests.factories import BookCopyFactory


async def _borrow_book(session, user, book, *, school_id=None):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=school_id or user.school_id,
        state=BooksStates.BORROWED,
        code=f'FAVORITE-{book.id}-{user.id}',
    )
    session.add(copy)
    await session.flush()
    session.add(
        Loan(
            copy_id=copy.id,
            user_id=user.id,
            school_id=school_id or user.school_id,
            due_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
    )
    await session.commit()
    return copy


@pytest.mark.asyncio
async def test_favorite_lifecycle_is_idempotent(session, client, student, student_token, book):
    await _borrow_book(session, student, book)
    headers = {'Authorization': f'Bearer {student_token}'}

    added = client.put(f'/books/{book.id}/favorite', headers=headers)
    assert added.status_code == HTTPStatus.OK
    assert added.json() == {'book_id': book.id, 'is_favorite': True}

    repeated = client.put(f'/books/{book.id}/favorite', headers=headers)
    assert repeated.status_code == HTTPStatus.OK

    current = client.get(f'/books/{book.id}/favorite', headers=headers)
    assert current.json()['is_favorite'] is True

    removed = client.delete(f'/books/{book.id}/favorite', headers=headers)
    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert client.get(f'/books/{book.id}/favorite', headers=headers).json() == {
        'book_id': book.id,
        'is_favorite': False,
    }

    # Deleting an already absent favorite is intentionally idempotent.
    assert client.delete(f'/books/{book.id}/favorite', headers=headers).status_code == HTTPStatus.NO_CONTENT


@pytest.mark.asyncio
async def test_favorite_requires_student_and_prior_loan(client, token, book, student, student_token):
    librarian_response = client.put(
        f'/books/{book.id}/favorite',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert librarian_response.status_code == HTTPStatus.FORBIDDEN

    student_response = client.put(
        f'/books/{book.id}/favorite',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert student_response.status_code == HTTPStatus.FORBIDDEN
    assert 'borrowed' in student_response.json()['detail']


@pytest.mark.asyncio
async def test_favorite_hides_inactive_and_other_school_books(
    session, client, student, student_token, other_school, book
):
    headers = {'Authorization': f'Bearer {student_token}'}

    inactive = Book(title='Inactive favorite', added_by=student.id, is_active=False)
    session.add(inactive)
    await session.flush()
    inactive_copy = BookCopyFactory(
        book_id=inactive.id,
        user_id=student.id,
        school_id=student.school_id,
        state=BooksStates.BORROWED,
        code='FAVORITE-INACTIVE',
    )
    session.add(inactive_copy)

    foreign = Book(title='Foreign favorite', added_by=student.id)
    session.add(foreign)
    await session.flush()
    foreign_copy = BookCopyFactory(
        book_id=foreign.id,
        user_id=student.id,
        school_id=other_school.id,
        state=BooksStates.BORROWED,
        code='FAVORITE-FOREIGN',
    )
    session.add(foreign_copy)
    await session.commit()

    for hidden in (inactive, foreign):
        response = client.get(f'/books/{hidden.id}/favorite', headers=headers)
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_favorite_requires_school_and_scopes_loan_to_school(
    session, client, student, student_token, other_school, book
):
    student_without_school = type(student)(
        username='without-school',
        name='Without school',
        password=None,
        role=UserRole.STUDENT,
        school_id=None,
    )
    with pytest.raises(HTTPException) as no_school:
        await favorites_router._student(student_without_school)
    assert no_school.value.status_code == HTTPStatus.FORBIDDEN

    copy = await _borrow_book(session, student, book, school_id=other_school.id)
    with pytest.raises(HTTPException) as foreign:
        await favorites_router._ensure_borrowed(session, book.id, student)
    assert foreign.value.status_code == HTTPStatus.FORBIDDEN
    assert copy.school_id == other_school.id

    assert await session.scalar(select(UserBookFavorite)) is None
