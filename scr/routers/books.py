from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import Book, BookCopy, User, UserRole
from scr.schemas import (
    BookCopyPublic,
    BookCopySchema,
    BookList,
    BooksPublic,
    BooksSchema,
    BookUpdate,
    FilterBook,
    Message,
)
from scr.security import get_current_user
from scr.utils.apis import get_google_book_info

router = APIRouter(tags=['books'], prefix='/books')

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post('/', response_model=BooksPublic, status_code=HTTPStatus.CREATED)
async def create_book(
    book: BooksSchema,
    session: Session,
    user: CurrentUser,
):
    if book.isbn:
        existing = await session.scalar(
            select(Book).where(Book.isbn == book.isbn)
        )
        if existing:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='This Book already exists',
            )

    # Google Books enrichment only for optional description
    description = book.description
    if book.isbn and not description:
        google_data = await get_google_book_info(book.isbn)
        description = description or google_data.get('description')

    db_book = Book(
        title=book.title,
        description=description,
        state=book.state,
        user_id=user.id,
        isbn=book.isbn,
    )

    session.add(db_book)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='This Book already exists',
        )

    await session.refresh(db_book)
    return db_book


@router.post(
    '/{book_id}/copies/',
    response_model=BookCopyPublic,
    status_code=HTTPStatus.CREATED,
)
async def create_book_copy(
    book_id: int,
    copy: BookCopySchema,
    session: Session,
    user: CurrentUser,
):
    # School-scoped users must have a school
    if user.role != UserRole.SUPER_ADMIN and user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User without school cannot create copies',
        )

    book = await session.scalar(select(Book).where(Book.id == book_id))

    if not book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )

    # Copies belong to the creator's school
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='SUPER_ADMIN cannot create copies',
        )

    # Code uniqueness is scoped per school
    existing_copy = await session.scalar(
        select(BookCopy).where(
            BookCopy.school_id == user.school_id,
            BookCopy.code == copy.code,
        )
    )
    if existing_copy:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='This Copy already exists',
        )

    db_copy = BookCopy(
        **copy.model_dump(),
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    session.add(db_copy)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='This Copy already exists',
        )

    await session.refresh(db_copy)
    return db_copy


@router.get('/', response_model=BookList)
async def list_books(
    session: Session,
    user: CurrentUser,
    book_filter: Annotated[FilterBook, Depends()],
):
    sttm = select(Book)

    # Tenant isolation: school users only see books with copies in their school
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot list books',
            )
        sttm = sttm.where(
            exists().where(
                (BookCopy.book_id == Book.id)
                & (BookCopy.school_id == user.school_id)
            )
        )

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
async def delete_book(
    book_id: int,
    session: Session,
    user: CurrentUser,
):
    # Only SUPER_ADMIN can delete global catalog entries
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Not enough permissions',
        )
    book = await session.scalar(select(Book).where(Book.id == book_id))

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
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Not enough permissions',
        )
    db_book = await session.scalar(select(Book).where(Book.id == book_id))

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
