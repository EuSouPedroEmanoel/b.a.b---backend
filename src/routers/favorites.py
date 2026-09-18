from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Book, BookCopy, Loan, User, UserBookFavorite, UserRole
from src.schemas import BookFavoritePublic
from src.security import get_current_user, is_guest

router = APIRouter(tags=['favorites'], prefix='/books')
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _student(user: User) -> User:
    if is_guest(user) or user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Only students can manage book favorites',
        )
    if user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Student without school cannot manage book favorites',
        )
    return user


async def _visible_book(
    session: AsyncSession, book_id: int, user: User
) -> Book:
    book = await session.scalar(select(Book).where(Book.id == book_id))
    if not book or not book.is_active:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )
    has_copies = await session.scalar(
        select(BookCopy.id).where(BookCopy.book_id == book_id).limit(1)
    )
    if has_copies is not None:
        in_school = await session.scalar(
            select(BookCopy.id)
            .where(
                BookCopy.book_id == book_id,
                BookCopy.school_id == user.school_id,
            )
            .limit(1)
        )
        if in_school is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
            )
    return book


async def _ensure_borrowed(
    session: AsyncSession, book_id: int, user: User
) -> None:
    borrowed = await session.scalar(
        select(Loan.id)
        .join(BookCopy, BookCopy.id == Loan.copy_id)
        .where(
            Loan.user_id == user.id,
            Loan.school_id == user.school_id,
            BookCopy.book_id == book_id,
        )
        .limit(1)
    )
    if borrowed is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Book must have been borrowed before it can be favorited',
        )


async def _favorite(
    session: AsyncSession, book_id: int, user_id: int
) -> UserBookFavorite | None:
    return await session.scalar(
        select(UserBookFavorite).where(
            UserBookFavorite.user_id == user_id,
            UserBookFavorite.book_id == book_id,
        )
    )


@router.get('/{book_id}/favorite', response_model=BookFavoritePublic)
async def get_favorite(
    book_id: int, session: Session, user: CurrentUser
):
    await _student(user)
    await _visible_book(session, book_id, user)
    await _ensure_borrowed(session, book_id, user)
    return {
        'book_id': book_id,
        'is_favorite': await _favorite(session, book_id, user.id) is not None,
    }


@router.put('/{book_id}/favorite', response_model=BookFavoritePublic)
async def add_favorite(
    book_id: int, session: Session, user: CurrentUser
):
    await _student(user)
    await _visible_book(session, book_id, user)
    await _ensure_borrowed(session, book_id, user)
    item = await _favorite(session, book_id, user.id)
    if item is None:
        session.add(UserBookFavorite(user_id=user.id, book_id=book_id))
        await session.commit()
    return {'book_id': book_id, 'is_favorite': True}


@router.delete('/{book_id}/favorite', status_code=HTTPStatus.NO_CONTENT)
async def remove_favorite(
    book_id: int, session: Session, user: CurrentUser
):
    await _student(user)
    await _visible_book(session, book_id, user)
    await _ensure_borrowed(session, book_id, user)
    item = await _favorite(session, book_id, user.id)
    if item is not None:
        await session.delete(item)
        await session.commit()
