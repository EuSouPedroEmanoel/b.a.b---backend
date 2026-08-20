from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import Book, User
from scr.schemas import (
    BookList,
    BooksPublic,
    BooksSchema,
    BookUpdate,
    FilterBook,
    Message,
)
from scr.security import get_current_user

router = APIRouter(tags=['books'], prefix='/books')

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post('/', response_model=BooksPublic, status_code=HTTPStatus.CREATED)
async def create_book(
    book: BooksSchema,
    session: Session,
    user: CurrentUser,
):
    db_book = Book(
        title=book.title,
        description=book.description,
        state=book.state,
        user_id=user.id,
        isbn=book.isbn,
        internal_code=book.internal_code
    )

    session.add(db_book)
    await session.commit()
    await session.refresh(db_book)
    return db_book


@router.get('/', response_model=BookList)
async def list_books(
    session: Session,
    user: CurrentUser,
    book_filter: Annotated[FilterBook, Depends()],
):
    sttm = select(Book).where(Book.user_id == user.id)

    if book_filter.title:
        sttm = sttm.where(Book.title.contains(book_filter.title))
    if book_filter.description:
        sttm = sttm.where(Book.description.contains(book_filter.description))
    if book_filter.state:
        sttm = sttm.where(Book.state == book_filter.state)

    books = await session.scalars(
        sttm.limit(book_filter.limit).offset(book_filter.offset)
    )

    return {'books': books.all()}


@router.delete('/{book_id}', response_model=Message)
async def delete_book(book_id: int, session: Session, user: CurrentUser):
    book = await session.scalar(
        select(Book).where(Book.user_id == user.id, Book.id == book_id)
    )

    if not book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )

    await session.delete(book)
    await session.commit()

    return {'message': 'Book has been deleted successfully.'}


@router.patch('/{book_id}', response_model=BooksPublic)
async def patch_book(
    book_id: int, session: Session, user: CurrentUser, book: BookUpdate
):
    db_book = await session.scalar(
        select(Book).where(Book.user_id == user.id, Book.id == book_id)
    )

    if not db_book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )

    for key, value in book.model_dump(exclude_unset=True).items():
        setattr(db_book, key, value)

    session.add(db_book)
    await session.commit()
    await session.refresh(db_book)

    return db_book
