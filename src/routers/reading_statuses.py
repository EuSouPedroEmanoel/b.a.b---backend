from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_session
from src.models import (
    Author,
    Book,
    BookCopy,
    Genre,
    Loan,
    ReadingStatus,
    User,
    UserReadingStatus,
    UserRole,
    book_authors,
)
from src.routers.books import (
    book_payload,
    copies_counts,
    derived_states,
)
from src.schemas import (
    BooksPublic,
    FilterPage,
    PaginatedResponse,
    ReadingStatusPublic,
    ReadingStatusUpdate,
)
from src.security import get_current_user, is_guest
from src.services.book_catalog import resolve_books
from src.utils.pagination import paginate

router = APIRouter(tags=['reading-statuses'], prefix='/reading-statuses')
book_router = APIRouter(tags=['reading-statuses'], prefix='/books')
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _student(user: User) -> User:
    if is_guest(user) or user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Only students can manage reading statuses',
        )
    if user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Student without school cannot manage reading statuses',
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


@router.get('/me', response_model=PaginatedResponse[BooksPublic])
async def list_my_reading_statuses(  # noqa: PLR0913, PLR0914, PLR0917
    session: Session,
    user: CurrentUser,
    status: ReadingStatus | None = None,
    borrowed_only: bool = False,
    genre_id: int | None = None,
    is_active: bool | None = True,
    sort_by: Literal[
        'title', 'created_at', 'published_date', 'author', 'updated_at'
    ] = 'updated_at',
    sort_order: Literal['asc', 'desc'] = 'desc',
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 15,
):
    await _student(user)
    query = (
        select(UserReadingStatus)
        .options(
            selectinload(UserReadingStatus.book).selectinload(Book.genres),
            selectinload(UserReadingStatus.book).selectinload(Book.authors),
        )
        .join(UserReadingStatus.book)
        .where(UserReadingStatus.user_id == user.id)
    )
    if is_active is not None:
        query = query.where(Book.is_active.is_(is_active))
    if status is not None:
        query = query.where(UserReadingStatus.status == status)
    if genre_id is not None:
        query = query.where(Book.genres.any(Genre.id == genre_id))
    if borrowed_only:
        query = query.where(
            exists(
                select(1)
                .select_from(Loan)
                .join(BookCopy, BookCopy.id == Loan.copy_id)
                .where(
                    Loan.user_id == user.id,
                    BookCopy.book_id == UserReadingStatus.book_id,
                )
            )
        )
    author_sort = (
        select(Author.name)
        .select_from(
            book_authors.join(Author, Author.id == book_authors.c.author_id)
        )
        .where(book_authors.c.book_id == Book.id)
        .order_by(Author.name.asc())
        .limit(1)
        .scalar_subquery()
    )
    sort_columns = {
        'title': Book.title,
        'created_at': Book.created_at,
        'published_date': Book.published_date,
        'author': author_sort,
        'updated_at': UserReadingStatus.updated_at,
    }
    sort_column = sort_columns[sort_by]
    query = query.order_by(
        sort_column.desc().nulls_last()
        if sort_order == 'desc'
        else sort_column.asc().nulls_last(),
        UserReadingStatus.book_id.desc()
        if sort_order == 'desc'
        else UserReadingStatus.book_id.asc(),
    )
    rows, total, current_page, current_size, pages = await paginate(
        session, query, FilterPage(page=page, size=size)
    )
    books = [row.book for row in rows]
    book_ids = [book.id for book in books]
    effective_books = await resolve_books(session, books, user.school_id)
    derived_list = await derived_states(session, book_ids, user.school_id)
    total_map, available_map = await copies_counts(
        session, book_ids, user.school_id
    )
    result = [
        {
            **book_payload(book, effective),
            'derived_state': derived,
            'total_copies': total_map.get(book.id, 0),
            'available_copies': available_map.get(book.id, 0),
            'reading_status': row.status,
        }
        for row, book, effective, derived in zip(
            rows, books, effective_books, derived_list
        )
    ]
    return {
        'items': result,
        'total': total,
        'page': current_page,
        'size': current_size,
        'pages': pages,
    }


@router.get(
    '/books/{book_id}/reading-status', response_model=ReadingStatusPublic
)
@book_router.get(
    '/{book_id}/reading-status', response_model=ReadingStatusPublic
)
async def get_reading_status(
    book_id: int, session: Session, user: CurrentUser
):
    await _student(user)
    await _visible_book(session, book_id, user)
    item = await session.scalar(
        select(UserReadingStatus).where(
            UserReadingStatus.user_id == user.id,
            UserReadingStatus.book_id == book_id,
        )
    )
    if item is None:
        return {'book_id': book_id, 'status': None}
    return item


@router.put(
    '/books/{book_id}/reading-status', response_model=ReadingStatusPublic
)
@book_router.put(
    '/{book_id}/reading-status', response_model=ReadingStatusPublic
)
async def set_reading_status(
    book_id: int,
    payload: ReadingStatusUpdate,
    session: Session,
    user: CurrentUser,
):
    await _student(user)
    await _visible_book(session, book_id, user)
    item = await session.scalar(
        select(UserReadingStatus).where(
            UserReadingStatus.user_id == user.id,
            UserReadingStatus.book_id == book_id,
        )
    )
    if item is None:
        item = UserReadingStatus(
            user_id=user.id, book_id=book_id, status=payload.status
        )
        session.add(item)
    else:
        item.status = payload.status
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        item = await session.scalar(
            select(UserReadingStatus).where(
                UserReadingStatus.user_id == user.id,
                UserReadingStatus.book_id == book_id,
            )
        )
        if item is None:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='Could not save reading status',
            )
        item.status = payload.status
        await session.commit()
    await session.refresh(item)
    return item


@router.delete(
    '/books/{book_id}/reading-status', status_code=HTTPStatus.NO_CONTENT
)
@book_router.delete(
    '/{book_id}/reading-status', status_code=HTTPStatus.NO_CONTENT
)
async def delete_reading_status(
    book_id: int, session: Session, user: CurrentUser
):
    await _student(user)
    await _visible_book(session, book_id, user)
    item = await session.scalar(
        select(UserReadingStatus).where(
            UserReadingStatus.user_id == user.id,
            UserReadingStatus.book_id == book_id,
        )
    )
    if item is not None:
        await session.delete(item)
        await session.commit()
