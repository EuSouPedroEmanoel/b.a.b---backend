import re
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Book, BookCopy, BooksStates, User, UserRole
from src.schemas import (
    BookCopyPublic,
    BookCopySchema,
    BookLookupResponse,
    BookResolveResponse,
    BooksPublic,
    BooksSchema,
    BookSuggestResponse,
    BookUpdate,
    FilterBook,
    Message,
    PaginatedResponse,
)
from src.security import RoleChecker, get_current_user
from src.utils.apis import get_google_book_info
from src.utils.pagination import paginate

ISBN_MIN_LENGTH = 10

router = APIRouter(tags=['books'], prefix='/books')

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
StaffOnly = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
            UserRole.SUPER_ADMIN,
        ])
    ),
]
# Para lookup/cadastro: só librarian e school_admin (super_admin não cadastra)
StaffCreateOnly = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
        ])
    ),
]


@router.get('/lookup', response_model=BookLookupResponse)
async def lookup_book(
    isbn: str,
    session: Session,
    user: StaffCreateOnly,
):
    raw = isbn.strip()
    clean = raw.replace('-', '').replace(' ', '')
    if len(clean) < ISBN_MIN_LENGTH:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail='ISBN inválido',
        )
    # ISBN pode estar salvo com ou sem hífens — verifica ambas as formas
    existing = await session.scalar(
        select(Book).where((Book.isbn == raw) | (Book.isbn == clean))
    )
    # fallback: compara sem hífens via Python se ainda não achou
    # (evita func.replace no PG)
    if not existing:
        all_with_isbn = await session.scalars(
            select(Book).where(Book.isbn.is_not(None))
        )
        for b in all_with_isbn:
            if b.isbn and b.isbn.replace('-', '').replace(' ', '') == clean:
                existing = b
                break
    if existing:
        return BookLookupResponse(
            isbn=clean,
            title=existing.title,
            description=existing.description,
            cover_url=existing.cover_url,
            found=True,
            already_exists=True,
            existing_book_id=existing.id,
        )
    data = await get_google_book_info(clean)
    return BookLookupResponse(
        isbn=clean,
        title=data.get('title'),
        description=data.get('description'),
        cover_url=data.get('cover_url'),
        found=bool(data.get('title')),
        already_exists=False,
        existing_book_id=None,
    )


@router.get('/resolve', response_model=BookResolveResponse)
async def resolve_book(
    term: str,
    session: Session,
    user: CurrentUser,
):
    raw = term.strip()
    clean = raw.replace('-', '').replace(' ', '')
    is_isbn = (
        bool(re.fullmatch(r'[0-9\- ]{10,17}', raw))
        and len(clean) >= ISBN_MIN_LENGTH
    )

    # 1) ISBN primeiro — match exato normalizado (com/sem hífens)
    if is_isbn:
        existing = await session.scalar(
            select(Book).where((Book.isbn == raw) | (Book.isbn == clean))
        )
        if not existing:
            all_with_isbn = await session.scalars(
                select(Book).where(Book.isbn.is_not(None))
            )
            for b in all_with_isbn:
                if b.isbn and b.isbn.replace('-', '').replace(' ', '') == clean:  # noqa: E501
                    existing = b
                    break
        if existing:
            return BookResolveResponse(kind='isbn', book_id=existing.id)
        return BookResolveResponse(kind='none', book_id=None)

    # 2) internal_code: match EXATO com BookCopy.code dentro da escola (tenant)
    q = select(Book.id).join(BookCopy, BookCopy.book_id == Book.id)
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot resolve book',
            )
        q = q.where(BookCopy.school_id == user.school_id)
    book_id = await session.scalar(q.where(BookCopy.code == raw))
    if book_id is not None:
        return BookResolveResponse(kind='internal_code', book_id=book_id)

    return BookResolveResponse(kind='title', book_id=None)


@router.get('/suggest', response_model=BookSuggestResponse)
async def suggest_books(
    q: str,
    session: Session,
    user: CurrentUser,
    limit: int = 5,
):
    raw = q.strip()
    if not raw:
        return BookSuggestResponse(items=[])
    sttm = (
        select(Book)
        .where(Book.is_active.is_(True))
        .where(Book.title.ilike(f'%{raw}%'))
        .order_by(Book.title)
        .limit(min(limit, 10))
    )
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot suggest books',
            )
        sttm = sttm.where(
            exists().select_from(BookCopy).where(
                (BookCopy.book_id == Book.id)
                & (BookCopy.school_id == user.school_id)
            )
        )
    books = await session.scalars(sttm)
    return BookSuggestResponse(items=list(books.all()))


@router.post('/', response_model=BooksPublic, status_code=HTTPStatus.CREATED)
async def create_book(
    book: BooksSchema,
    session: Session,
    user: StaffCreateOnly,
):
    # Normalize isbn: remove hífens/espaços para unicidade
    # (978-0-00-000001-1 == 9780000000011)
    raw_isbn = (book.isbn or '').strip() or None
    isbn = raw_isbn.replace('-', '').replace(' ', '') if raw_isbn else None
    if isbn:
        existing = await session.scalar(
            select(Book).where((Book.isbn == raw_isbn) | (Book.isbn == isbn))
        )
        if not existing:
            all_with_isbn = await session.scalars(
                select(Book).where(Book.isbn.is_not(None))
            )
            for b in all_with_isbn:
                if b.isbn and b.isbn.replace('-', '').replace(' ', '') == isbn:
                    existing = b
                    break
        if existing:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='This Book already exists',
            )

    # Enrich missing title/description via external API when isbn is provided
    title = (book.title or '').strip() or None
    description = book.description
    cover_url = book.cover_url

    google_data = (
        await get_google_book_info(isbn) if isbn else {}
    )
    if isbn:
        title = title or google_data.get('title')
        description = description or google_data.get('description')
        cover_url = cover_url or google_data.get('cover_url')

    if not title:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail='Book information not found',
        )

    db_book = Book(
        title=title,
        description=description,
        cover_url=cover_url,
        added_by=user.id,
        isbn=isbn,
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
    user: StaffOnly,
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
        added_by=user.id,
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


def _book_public(book: Book) -> dict:
    return {
        'id': book.id,
        'title': book.title,
        'description': book.description,
        'isbn': book.isbn,
        'cover_url': book.cover_url,
        'is_active': book.is_active,
        'added_by': book.added_by,
        'edited_by': book.edited_by,
    }


async def _derived_states(
    session: AsyncSession,
    book_ids: list[int],
    school_scope: int | None,
) -> list[BooksStates]:
    """Derived states for each book_id, scoped to a school (in order)."""
    if not book_ids:
        return []
    q = select(BookCopy.book_id, BookCopy.state).where(
        BookCopy.book_id.in_(book_ids)
    )
    if school_scope is not None:
        q = q.where(BookCopy.school_id == school_scope)
    rows = (await session.execute(q)).all()
    has_available: dict[int, bool] = {}
    for bid, st in rows:
        if st == BooksStates.AVAILABLE:
            has_available[bid] = True
        else:
            has_available.setdefault(bid, False)
    return [
        (
            BooksStates.AVAILABLE
            if has_available.get(bid)
            else BooksStates.BORROWED if bid in has_available
            else BooksStates.ARCHIVED
        )
        for bid in book_ids
    ]


@router.get('/', response_model=PaginatedResponse[BooksPublic])
async def list_books(
    session: Session,
    user: CurrentUser,
    book_filter: Annotated[FilterBook, Depends()],
):
    school_scope = (
        None if user.role == UserRole.SUPER_ADMIN else user.school_id
    )

    sttm = select(Book).order_by(Book.id)

    # default: hide inactive books unless explicitly requested
    if book_filter.is_active is None:
        sttm = sttm.where(Book.is_active.is_(True))
    else:
        sttm = sttm.where(Book.is_active.is_(book_filter.is_active))

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

    if book_filter.q:
        raw = book_filter.q.strip()
        clean = raw.replace('-', '').replace(' ', '')
        cond_title = Book.title.ilike(f'%{raw}%')
        cond_isbn = (Book.isbn == raw) | (Book.isbn == clean)
        cond_copy = exists().where(
            (BookCopy.book_id == Book.id) & (BookCopy.code == raw)
        )
        if user.role != UserRole.SUPER_ADMIN:
            cond_copy = exists().where(
                (BookCopy.book_id == Book.id)
                & (BookCopy.code == raw)
                & (BookCopy.school_id == user.school_id)
            )
        sttm = sttm.where(cond_title | cond_isbn | cond_copy)

    if book_filter.title:
        sttm = sttm.where(Book.title.contains(book_filter.title))
    if book_filter.description:
        sttm = sttm.where(Book.description.contains(book_filter.description))
    if book_filter.state:
        sttm = sttm.where(
            Book.derived_state_expr(school_scope) == book_filter.state
        )
    if book_filter.isbn:
        clean_isbn = book_filter.isbn.replace('-', '').replace(' ', '')
        sttm = sttm.where(
            (Book.isbn == book_filter.isbn) | (Book.isbn == clean_isbn)
        )
    if book_filter.internal_code:
        copy_filter = exists().where(
            (BookCopy.book_id == Book.id)
            & (BookCopy.code == book_filter.internal_code)
        )
        sttm = sttm.where(copy_filter)

    items, total, page, size, pages = await paginate(
        session, sttm, book_filter
    )

    result = [
        {**_book_public(b), 'derived_state': st}
        for b, st in zip(items, await _derived_states(
            session, [b.id for b in items], school_scope
        ))
    ]

    return {
        'items': result,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/{book_id}', response_model=BooksPublic)
async def get_book(
    book_id: int,
    session: Session,
    user: CurrentUser,
):
    school_scope = (
        None if user.role == UserRole.SUPER_ADMIN else user.school_id
    )

    book = await session.scalar(select(Book).where(Book.id == book_id))
    if not book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )

    # Tenant isolation: school users can only open books with copies in school
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot access books',
            )
        in_school = await session.scalar(
            select(BookCopy.id)
            .where(
                (BookCopy.book_id == book.id)
                & (BookCopy.school_id == user.school_id)
            )
            .limit(1)
        )
        if in_school is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
            )

    derived = (await _derived_states(session, [book.id], school_scope))[0]
    return {**_book_public(book), 'derived_state': derived}


@router.delete('/{book_id}', response_model=Message)
async def delete_book(
    book_id: int,
    session: Session,
    user: StaffOnly,
):
    # Only SUPER_ADMIN can delete (soft delete) global catalog entries
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

    # soft delete
    book.is_active = False
    book.edited_by = user.id
    session.add(book)
    await session.commit()

    return {'message': 'Book has been deactivated successfully.'}


@router.patch('/{book_id}', response_model=BooksPublic)
async def patch_book(
    book_id: int, session: Session, user: StaffOnly, book: BookUpdate
):
    # Librarian e school_admin podem corrigir dados de livro já cadastrado
    # (scan → editar)
    if user.role not in {
        UserRole.SUPER_ADMIN,
        UserRole.LIBRARIAN,
        UserRole.SCHOOL_ADMIN,
    }:
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

    db_book.edited_by = user.id
    session.add(db_book)
    await session.commit()
    await session.refresh(db_book)

    return db_book
