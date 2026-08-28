from dataclasses import asdict

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, UserRole
from tests.factories import BookCopyFactory, BookFactory


@pytest.mark.asyncio
async def test_create_user(session: AsyncSession, mock_db_time):
    with mock_db_time(model=User) as time:
        new_user = User(
            username='test',
            email='test@test',
            password='secret',
            role=UserRole.SUPER_ADMIN,
        )

        session.add(new_user)
        await session.commit()

        sttm = select(User).where(User.username == 'test')

        user = await session.scalar(sttm)

    assert asdict(user) == {
        'id': 1,
        'username': 'test',
        'email': 'test@test',
        'password': 'secret',
        'role': UserRole.SUPER_ADMIN,
        'school_id': None,
        'is_active': True,
        'school': None,
        'created_at': time,
        'updated_at': time,
        'books': [],
        'copies': [],
        'cpf': None,
        'birthdate': None,
        'turma_numero': None,
        'turma_letra': None,
    }


@pytest.mark.asyncio
async def test_wrong_enum_in_create_copy(user, session):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    copy = BookCopyFactory.build(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state='invalid',
    )
    session.add(copy)
    with pytest.raises(StatementError):
        await session.commit()
