from dataclasses import asdict

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from scr.models import User
from tests.factories import BookFactory


@pytest.mark.asyncio
async def test_create_user(session: AsyncSession, mock_db_time):
    with mock_db_time(model=User) as time:
        new_user = User(username='test', email='test@test', password='secret')

        session.add(new_user)
        await session.commit()

        sttm = select(User).where(User.username == 'test')

        user = await session.scalar(sttm)

    assert asdict(user) == {
        'id': 1,
        'username': 'test',
        'email': 'test@test',
        'password': 'secret',
        'created_at': time,
        'updated_at': time,
        'books': [],
    }


@pytest.mark.asyncio
async def test_wrong_enum_in_create_book(user, session):
    book = BookFactory.build(
        isbn='978-3-16-148410-0', user_id=user.id, state='invalid'
    )
    session.add(book)
    with pytest.raises(StatementError):
        await session.commit()
