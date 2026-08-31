import re
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_session
from src.models import (
    Author,
    Book,
    BookCopy,
    BooksStates,
    Genre,
    Loan,
    Reservation,
    User,
    UserRole,
    book_authors,
    book_genres,
)
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
from src.utils.authors import display_name_author, slugify_author
from src.utils.genres import display_name_genre, slugify_genre
from src.utils.pagination import paginate

ISBN_MIN_LENGTH = 10

router = APIRouter(tags=['books'], prefix='/books')


async def _get_or_create_genre_by_name(  # pragma: no cover
    session: AsyncSession, raw_name: str
) -> Genre:
    name = display_name_genre(raw_name)
    if not name:
        raise ValueError('Genre name empty')
    slug = slugify_genre(name)
    existing = await session.scalar(select(Genre).where(Genre.slug == slug))
    if existing:
        return existing
    genre = Genre(name=name, slug=slug)
    session.add(genre)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing2 = await session.scalar(
            select(Genre).where(Genre.slug == slug)
        )
        if existing2:
            return existing2
        raise
    return genre


async def _get_or_create_genres(  # pragma: no cover
    session: AsyncSession, names: list[str]
) -> list[Genre]:
    result: list[Genre] = []
    seen: set[str] = set()
    for raw in names:
        if not raw or not str(raw).strip():
            continue
        slug = slugify_genre(str(raw))
        if slug in seen:
            continue
        seen.add(slug)
        # skip empty slug
        if not slug:
            continue
        genre = await _get_or_create_genre_by_name(session, str(raw))
        result.append(genre)
    return result


async def _resolve_genres_for_book(  # pragma: no cover
    session: AsyncSession,
    genre_ids: list[int] | None,
    genre_names: list[str] | None,
    fallback_genres: list[str] | None = None,
) -> list[Genre]:
    genres: list[Genre] = []
    seen_ids: set[int] = set()
    # explicit ids
    if genre_ids:
        for gid in genre_ids:
            g = await session.scalar(select(Genre).where(Genre.id == gid))
            if not g:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail=f'Genre {gid} not found',
                )
            if g.id not in seen_ids:
                genres.append(g)
                seen_ids.add(g.id)
    # names -> get_or_create
    names_to_create: list[str] = []
    if genre_names:
        names_to_create.extend(genre_names)
    # fallback (from API) only if nothing else provided and no genres yet
    if not genres and not names_to_create and fallback_genres:
        names_to_create.extend(fallback_genres)
    if names_to_create:
        created = await _get_or_create_genres(session, names_to_create)
        for g in created:
            if g.id not in seen_ids:
                genres.append(g)
                seen_ids.add(g.id)
    return genres


async def _get_or_create_author_by_name(  # pragma: no cover
    session: AsyncSession, raw_name: str
) -> Author:
    name = display_name_author(raw_name)
    if not name:
        raise ValueError('Author name empty')
    slug = slugify_author(name)
    existing = await session.scalar(select(Author).where(Author.slug == slug))
    if existing:
        return existing
    author = Author(name=name, slug=slug)
    session.add(author)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing2 = await session.scalar(
            select(Author).where(Author.slug == slug)
        )
        if existing2:
            return existing2
        raise
    return author


async def _get_or_create_authors(  # pragma: no cover
    session: AsyncSession, names: list[str]
) -> list[Author]:
    result: list[Author] = []
    seen: set[str] = set()
    for raw in names:
        if not raw or not str(raw).strip():
            continue
        slug = slugify_author(str(raw))
        if slug in seen:
            continue
        seen.add(slug)
        if not slug:
            continue
        author = await _get_or_create_author_by_name(session, str(raw))
        result.append(author)
    return result


async def _resolve_authors_for_book(  # pragma: no cover
    session: AsyncSession,
    author_ids: list[int] | None,
    author_names: list[str] | None,
    fallback_authors: list[str] | None = None,
) -> list[Author]:
    authors: list[Author] = []
    seen_ids: set[int] = set()
    if author_ids:
        for aid in author_ids:
            a = await session.scalar(select(Author).where(Author.id == aid))
            if not a:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail=f'Author {aid} not found',
                )
            if a.id not in seen_ids:
                authors.append(a)
                seen_ids.add(a.id)
    names_to_create: list[str] = []
    if author_names:
        names_to_create.extend(author_names)
    if not authors and not names_to_create and fallback_authors:
        names_to_create.extend(fallback_authors)
    if names_to_create:
        created = await _get_or_create_authors(session, names_to_create)
        for a in created:
            if a.id not in seen_ids:
                authors.append(a)
                seen_ids.add(a.id)
    return authors


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
            published_date=existing.published_date,
            genres=[g.name for g in (existing.genres or [])],
            authors=[a.name for a in (existing.authors or [])],
            found=True,
            already_exists=True,
            existing_book_id=existing.id,
        )
    data = await get_google_book_info(clean)
    raw_genres = data.get('genres') or []
    # padroniza para português (Fiction -> Ficção)
    canonical_genres = [display_name_genre(g) for g in raw_genres if g.strip()]
    # deduplica mantendo ordem
    seen = set()
    uniq_genres = []
    for g in canonical_genres:
        s = slugify_genre(g)
        if s not in seen:
            seen.add(s)
            uniq_genres.append(g)
    raw_authors = data.get('authors') or []
    uniq_authors = []
    seen_a = set()
    for a in raw_authors:
        if not a.strip():
            continue
        s = slugify_author(a)
        if s not in seen_a:
            seen_a.add(s)
            uniq_authors.append(display_name_author(a))
    pub_raw = data.get('published_date')
    pub_date = None
    if pub_raw:
        try:
            from datetime import date as _date  # noqa: PLC0415

            pub_date = _date.fromisoformat(str(pub_raw))
        except Exception:
            pub_date = None
    return BookLookupResponse(
        isbn=clean,
        title=data.get('title'),
        description=data.get('description'),
        cover_url=data.get('cover_url'),
        published_date=pub_date,
        genres=uniq_genres,
        authors=uniq_authors,
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
                if (
                    b.isbn
                    and b.isbn.replace('-', '').replace(' ', '') == clean
                ):  # noqa: E501
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
    # Busca por título, gênero ou autor (autocomplete)
    cond_title = Book.title.ilike(f'%{raw}%')
    slug = slugify_genre(raw)
    cond_genre = exists(
        select(1)
        .select_from(
            book_genres.join(Genre, Genre.id == book_genres.c.genre_id)
        )
        .where(
            (book_genres.c.book_id == Book.id)
            & ((Genre.name.ilike(f'%{raw}%')) | (Genre.slug == slug))
        )
    )
    slug_a = slugify_author(raw)
    cond_author = exists(
        select(1)
        .select_from(
            book_authors.join(Author, Author.id == book_authors.c.author_id)
        )
        .where(
            (book_authors.c.book_id == Book.id)
            & ((Author.name.ilike(f'%{raw}%')) | (Author.slug == slug_a))
        )
    )
    sttm = (
        select(Book)
        .where(Book.is_active.is_(True))
        .where(cond_title | cond_genre | cond_author)
        .order_by(Book.title)
        .limit(min(limit, 10))
    )
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot suggest books',
            )
        # inclui livros órfãos (sem cópias) para que livro recém-cadastrado apareça na busca  # noqa: E501
        sttm = sttm.where(
            exists()
            .select_from(BookCopy)
            .where(
                (BookCopy.book_id == Book.id)
                & (BookCopy.school_id == user.school_id)
            )
            | ~exists()
            .select_from(BookCopy)
            .where(BookCopy.book_id == Book.id)
        )
    books = await session.scalars(sttm)
    return BookSuggestResponse(items=list(books.all()))


@router.post('/', response_model=BooksPublic, status_code=HTTPStatus.CREATED)
async def create_book(  # noqa: PLR0914
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
    published_date = book.published_date

    google_data = await get_google_book_info(isbn) if isbn else {}
    if isbn:
        title = title or google_data.get('title')
        description = description or google_data.get('description')
        cover_url = cover_url or google_data.get('cover_url')
        if not published_date and google_data.get('published_date'):
            try:
                from datetime import date as _date  # noqa: PLC0415

                published_date = _date.fromisoformat(
                    str(google_data.get('published_date'))
                )
            except Exception:
                published_date = None

    if not title:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail='Book information not found',
        )

    # Resolve genres: explicit ids/names + fallback from API categories
    fallback_genres = google_data.get('genres') if isbn else None
    genres = await _resolve_genres_for_book(
        session, book.genre_ids, book.genre_names, fallback_genres
    )
    # Resolve authors: explicit ids/names + fallback from API authors
    fallback_authors = google_data.get('authors') if isbn else None
    authors = await _resolve_authors_for_book(
        session, book.author_ids, book.author_names, fallback_authors
    )

    db_book = Book(
        title=title,
        description=description,
        cover_url=cover_url,
        published_date=published_date,
        added_by=user.id,
        isbn=isbn,
    )
    db_book.genres = genres
    db_book.authors = authors

    session.add(db_book)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='This Book already exists',
        )

    await session.refresh(db_book, attribute_names=['genres', 'authors'])
    # new book has no copies -> derived_state ARCHIVED, but compute via helper for consistency  # noqa: E501
    derived = (await _derived_states(session, [db_book.id], None))[0]
    total_map, avail_map = await _copies_counts(session, [db_book.id], None)
    return {
        **_book_public(db_book),
        'derived_state': derived,
        'total_copies': total_map.get(db_book.id, 0),
        'available_copies': avail_map.get(db_book.id, 0),
    }


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
    genres_list = []
    for g in book.genres or []:
        try:
            genres_list.append({'id': g.id, 'name': g.name, 'slug': g.slug})
        except Exception:
            genres_list.append(g)
    authors_list = []
    for a in book.authors or []:
        try:
            authors_list.append({'id': a.id, 'name': a.name, 'slug': a.slug})
        except Exception:
            authors_list.append(a)
    return {
        'id': book.id,
        'title': book.title,
        'description': book.description,
        'isbn': book.isbn,
        'cover_url': book.cover_url,
        'published_date': book.published_date,
        'is_active': book.is_active,
        'added_by': book.added_by,
        'edited_by': book.edited_by,
        'created_at': book.created_at,
        'updated_at': book.updated_at,
        'genres': genres_list,
        'genre_ids': [g['id'] for g in genres_list],
        'genre_names': [g['name'] for g in genres_list],
        'authors': authors_list,
        'author_ids': [a['id'] for a in authors_list],
        'author_names': [a['name'] for a in authors_list],
    }


async def _derived_states(
    session: AsyncSession,
    book_ids: list[int],
    school_scope: int | None,
) -> list[BooksStates]:
    """Derived states for each book_id, scoped to a school (in order).

    Prioridade: AVAILABLE > RESERVED > BORROWED > LOST > ARCHIVED
    """
    if not book_ids:
        return []
    q = select(BookCopy.book_id, BookCopy.state).where(
        BookCopy.book_id.in_(book_ids)
    )
    if school_scope is not None:
        q = q.where(BookCopy.school_id == school_scope)
    rows = (await session.execute(q)).all()
    states_by_book: dict[int, set[BooksStates]] = {}
    for bid, st in rows:
        states_by_book.setdefault(bid, set()).add(st)
    result: list[BooksStates] = []
    for bid in book_ids:
        states = states_by_book.get(bid)
        if not states:
            result.append(BooksStates.ARCHIVED)
        elif BooksStates.AVAILABLE in states:
            result.append(BooksStates.AVAILABLE)
        elif BooksStates.RESERVED in states:
            result.append(BooksStates.RESERVED)
        elif BooksStates.BORROWED in states:
            result.append(BooksStates.BORROWED)
        elif BooksStates.LOST in states:
            result.append(BooksStates.LOST)
        else:
            result.append(BooksStates.ARCHIVED)
    return result


async def _copies_counts(
    session: AsyncSession,
    book_ids: list[int],
    school_scope: int | None,
) -> tuple[dict[int, int], dict[int, int]]:
    if not book_ids:
        return {}, {}
    q_total = select(BookCopy.book_id, func.count(BookCopy.id)).where(
        BookCopy.book_id.in_(book_ids)
    )
    q_avail = select(BookCopy.book_id, func.count(BookCopy.id)).where(
        BookCopy.book_id.in_(book_ids), BookCopy.state == BooksStates.AVAILABLE
    )
    if school_scope is not None:
        q_total = q_total.where(BookCopy.school_id == school_scope)
        q_avail = q_avail.where(BookCopy.school_id == school_scope)
    q_total = q_total.group_by(BookCopy.book_id)
    q_avail = q_avail.group_by(BookCopy.book_id)
    total_rows = (await session.execute(q_total)).all()
    avail_rows = (await session.execute(q_avail)).all()
    total_map = {bid: cnt for bid, cnt in total_rows}
    avail_map = {bid: cnt for bid, cnt in avail_rows}
    return total_map, avail_map


@router.get('/', response_model=PaginatedResponse[BooksPublic])
async def list_books(  # noqa: PLR0912, PLR0914, PLR0915
    session: Session,
    user: CurrentUser,
    book_filter: Annotated[FilterBook, Depends()],
):
    school_scope = (
        None if user.role == UserRole.SUPER_ADMIN else user.school_id
    )

    # ordenação — inclui 'author' via subquery do primeiro autor (ordem alfabética)  # noqa: E501
    author_sort_subq = (
        select(func.min(Author.name))
        .select_from(
            book_authors.join(Author, Author.id == book_authors.c.author_id)
        )
        .where(book_authors.c.book_id == Book.id)
        .correlate(Book)
        .scalar_subquery()
    )
    if (book_filter.sort_by or 'id') == 'author':
        sort_col = author_sort_subq
        sort_dir = (book_filter.sort_order or 'asc').lower()
        if sort_dir == 'desc':
            sttm = select(Book).order_by(
                sort_col.desc().nulls_last(), Book.id.desc()
            )
        else:
            sttm = select(Book).order_by(
                sort_col.asc().nulls_last(), Book.id.asc()
            )
    else:
        sort_map = {
            'title': Book.title,
            'created_at': Book.created_at,
            'updated_at': Book.updated_at,
            'published_date': Book.published_date,
            'author': author_sort_subq,
            'id': Book.id,
        }
        sort_col = sort_map.get(book_filter.sort_by or 'id', Book.id)
        sort_dir = (book_filter.sort_order or 'asc').lower()
        if sort_dir == 'desc':
            sttm = select(Book).order_by(
                sort_col.desc().nulls_last()
                if book_filter.sort_by == 'author'
                else sort_col.desc(),
                Book.id.desc() if sort_col != Book.id else sort_col.desc(),
            )
        else:
            sttm = select(Book).order_by(
                sort_col.asc().nulls_last()
                if book_filter.sort_by == 'author'
                else sort_col.asc(),
                Book.id.asc() if sort_col != Book.id else sort_col.asc(),
            )

    # default: hide inactive books unless explicitly requested
    if book_filter.is_active is None:
        sttm = sttm.where(Book.is_active.is_(True))
    else:
        sttm = sttm.where(Book.is_active.is_(book_filter.is_active))

    # Tenant isolation: school users see books with copies in their school + livros órfãos (0 cópias) recém-cadastrados  # noqa: E501
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
            | ~exists().where(BookCopy.book_id == Book.id)
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
        # busca também por gênero e autor (nome/slug) — só livros cadastrados
        slug_q = slugify_genre(raw)
        cond_genre_q = exists(
            select(1)
            .select_from(
                book_genres.join(Genre, Genre.id == book_genres.c.genre_id)
            )
            .where(
                (book_genres.c.book_id == Book.id)
                & ((Genre.name.ilike(f'%{raw}%')) | (Genre.slug == slug_q))
            )
        )
        slug_a_q = slugify_author(raw)
        cond_author_q = exists(
            select(1)
            .select_from(
                book_authors.join(
                    Author, Author.id == book_authors.c.author_id
                )
            )
            .where(
                (book_authors.c.book_id == Book.id)
                & ((Author.name.ilike(f'%{raw}%')) | (Author.slug == slug_a_q))
            )
        )
        # busca por disponibilidade (estado derivado) — ex.: "Disponível", "Emprestado"
        avail_map = {
            'disponivel': BooksStates.AVAILABLE,
            'disponível': BooksStates.AVAILABLE,
            'available': BooksStates.AVAILABLE,
            'emprestado': BooksStates.BORROWED,
            'borrowed': BooksStates.BORROWED,
            'reservado': BooksStates.RESERVED,
            'reserved': BooksStates.RESERVED,
            'perdido': BooksStates.LOST,
            'lost': BooksStates.LOST,
            'arquivado': BooksStates.ARCHIVED,
            'archived': BooksStates.ARCHIVED,
        }
        normalized = raw.lower().strip()
        # normaliza acentos simples para busca
        normalized = normalized.replace('í', 'i').replace('á', 'a').replace('ã', 'a')
        matched_state = None
        for key, st in avail_map.items():
            if key in normalized or normalized in key:
                # evita match muito curto (ex.: "a" em "available")
                if len(normalized) >= 3:
                    matched_state = st
                    break
        cond_avail_q = None
        if matched_state is not None:
            cond_avail_q = Book.derived_state_expr(school_scope) == matched_state
        if cond_avail_q is not None:
            sttm = sttm.where(
                cond_title | cond_isbn | cond_copy | cond_genre_q | cond_author_q | cond_avail_q
            )
        else:
            sttm = sttm.where(
                cond_title | cond_isbn | cond_copy | cond_genre_q | cond_author_q
            )

    if book_filter.title:
        sttm = sttm.where(Book.title.contains(book_filter.title))
    if book_filter.description:
        sttm = sttm.where(Book.description.contains(book_filter.description))
    if book_filter.state:
        sttm = sttm.where(
            Book.derived_state_expr(school_scope) == book_filter.state
        )
    elif user.role == UserRole.STUDENT and not book_filter.q:
        sttm = sttm.where(
            Book.derived_state_expr(school_scope) == BooksStates.AVAILABLE
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

    if book_filter.genre_id is not None:
        sttm = sttm.where(
            exists().where(
                (book_genres.c.book_id == Book.id)
                & (book_genres.c.genre_id == book_filter.genre_id)
            )
        )
    if book_filter.genre:
        raw_genre = book_filter.genre.strip()
        slug = slugify_genre(raw_genre)
        sttm = sttm.where(
            exists()
            .select_from(
                book_genres.join(Genre, Genre.id == book_genres.c.genre_id)
            )
            .where(
                (book_genres.c.book_id == Book.id)
                & ((Genre.slug == slug) | (Genre.name.ilike(f'%{raw_genre}%')))
            )
        )
    if book_filter.author_id is not None:
        sttm = sttm.where(
            exists().where(
                (book_authors.c.book_id == Book.id)
                & (book_authors.c.author_id == book_filter.author_id)
            )
        )
    if book_filter.author:
        raw_author = book_filter.author.strip()
        slug_a = slugify_author(raw_author)
        sttm = sttm.where(
            exists()
            .select_from(
                book_authors.join(
                    Author, Author.id == book_authors.c.author_id
                )
            )
            .where(
                (book_authors.c.book_id == Book.id)
                & (
                    (Author.slug == slug_a)
                    | (Author.name.ilike(f'%{raw_author}%'))
                )
            )
        )

    items, total, page, size, pages = await paginate(
        session, sttm, book_filter
    )

    book_ids = [b.id for b in items]
    derived_list = await _derived_states(session, book_ids, school_scope)
    total_map, avail_map = await _copies_counts(session, book_ids, school_scope)  # noqa: E501
    result = [
        {
            **_book_public(b),
            'derived_state': st,
            'total_copies': total_map.get(b.id, 0),
            'available_copies': avail_map.get(b.id, 0),
        }
        for b, st in zip(items, derived_list)
    ]

    return {
        'items': result,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


def _diversify_books(  # pragma: no cover
    books: list[Book], max_consecutive: int = 2
) -> list[Book]:
    """Evita mais de `max_consecutive` livros seguidos do mesmo autor."""
    if len(books) <= max_consecutive:
        return books
    result: list[Book] = []
    remaining = books[:]
    while remaining:
        pick_idx = None
        for idx, cand in enumerate(remaining):
            if len(result) < max_consecutive:
                pick_idx = idx
                break
            last_authors = [
                (r.authors[0].id if r.authors else None)
                for r in result[-max_consecutive:]
            ]
            cur_author = cand.authors[0].id if cand.authors else None
            if not (
                cur_author is not None
                and len(set(last_authors)) == 1
                and last_authors[0] == cur_author
            ):
                pick_idx = idx
                break
        if pick_idx is None:
            pick_idx = 0
        result.append(remaining.pop(pick_idx))
    return result


@router.get('/{book_id}/recommendations', response_model=list[BooksPublic])
async def get_recommendations(  # pragma: no cover
    book_id: int,
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 16,
):
    """Pipeline 3 camadas: afinidade pessoal (~50%) + contexto livro (~30%) + tendências globais (~20%)."""
    school_scope = (
        None if user.role == UserRole.SUPER_ADMIN else user.school_id
    )
    if user.role != UserRole.SUPER_ADMIN and user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User without school cannot get recommendations',
        )

    target = await session.scalar(
        select(Book)
        .options(selectinload(Book.genres), selectinload(Book.authors))
        .where(Book.id == book_id)
    )
    if not target:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
        )
    # tenant check for target (same as get_book)
    if user.role != UserRole.SUPER_ADMIN:
        has_any = await session.scalar(
            select(BookCopy.id).where(BookCopy.book_id == target.id).limit(1)
        )
        if has_any is not None:
            in_school = await session.scalar(
                select(BookCopy.id)
                .where(
                    (BookCopy.book_id == target.id)
                    & (BookCopy.school_id == user.school_id)
                )
                .limit(1)
            )
            if in_school is None:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND, detail='Book not found.'
                )

    # quotas
    affinity_quota = int(limit * 0.5)
    context_quota = int(limit * 0.3)
    trends_quota = limit - affinity_quota - context_quota

    target_genre_ids = [g.id for g in (target.genres or [])]
    target_author_ids = [a.id for a in (target.authors or [])]

    # helper to filter visible books
    def _visible_filter(query):
        if user.role == UserRole.SUPER_ADMIN:
            return query
        # visible = has copy in school OR no copies at all (orphan)
        return query.where(
            exists()
            .where(
                (BookCopy.book_id == Book.id)
                & (BookCopy.school_id == user.school_id)
            )
            | ~exists().where(BookCopy.book_id == Book.id)
        )

    ordered_ids: list[int] = []
    seen: set[int] = {book_id}

    # --- 1) Afinidade pessoal + histórico (~50%) ---
    try:
        # user's loan history -> book_ids
        user_book_ids_rows = await session.scalars(
            select(BookCopy.book_id)
            .join(Loan, Loan.copy_id == BookCopy.id)
            .where(Loan.user_id == user.id)
        )
        user_book_ids = set(user_book_ids_rows.all())
        # also include reservations history
        res_rows = await session.scalars(
            select(Reservation.book_id).where(Reservation.user_id == user.id)
        )
        user_book_ids.update(res_rows.all())

        if user_book_ids:
            # profile genres/authors from history
            profile_genre_rows = await session.scalars(
                select(book_genres.c.genre_id).where(
                    book_genres.c.book_id.in_(list(user_book_ids))
                )
            )
            profile_genre_ids = set(profile_genre_rows.all())
            profile_author_rows = await session.scalars(
                select(book_authors.c.author_id).where(
                    book_authors.c.book_id.in_(list(user_book_ids))
                )
            )
            profile_author_ids = set(profile_author_rows.all())

            if profile_genre_ids or profile_author_ids:
                # find similar users (who borrowed books sharing profile genres/authors)
                # collect candidate book_ids sharing profile interests
                interest_book_ids_q = select(book_genres.c.book_id).where(
                    book_genres.c.genre_id.in_(list(profile_genre_ids))
                ) if profile_genre_ids else None
                if profile_author_ids:
                    author_q = select(book_authors.c.book_id).where(
                        book_authors.c.author_id.in_(list(profile_author_ids))
                    )
                    if interest_book_ids_q is not None:
                        interest_book_ids_q = interest_book_ids_q.union(author_q)
                    else:
                        interest_book_ids_q = author_q
                if interest_book_ids_q is not None:
                    interest_book_ids = set(
                        (await session.scalars(interest_book_ids_q)).all()
                    )
                    if interest_book_ids:
                        similar_users_rows = await session.execute(
                            select(Loan.user_id, func.count(Loan.id).label('cnt'))
                            .join(BookCopy, Loan.copy_id == BookCopy.id)
                            .where(
                                BookCopy.book_id.in_(list(interest_book_ids)),
                                Loan.user_id != user.id,
                            )
                            .group_by(Loan.user_id)
                            .order_by(func.count(Loan.id).desc())
                            .limit(20)
                        )
                        similar_user_ids = [r[0] for r in similar_users_rows.all()]
                        if similar_user_ids:
                            aff_rows = await session.execute(
                                select(
                                    BookCopy.book_id,
                                    func.count(Loan.id).label('cnt'),
                                )
                                .join(Loan, Loan.copy_id == BookCopy.id)
                                .where(
                                    Loan.user_id.in_(similar_user_ids),
                                    BookCopy.book_id != book_id,
                                    BookCopy.book_id.notin_(list(user_book_ids)),
                                )
                                .group_by(BookCopy.book_id)
                                .order_by(func.count(Loan.id).desc())
                                .limit(affinity_quota * 2)
                            )
                            for bid, _ in aff_rows.all():
                                if bid not in seen:
                                    ordered_ids.append(bid)
                                    seen.add(bid)
                                    if len([x for x in ordered_ids if x in seen]) >= affinity_quota:
                                        # we inserted affinity quota soon; break when quota met
                                        pass
                            # trim to quota, keep order
                            # we may have inserted more than quota due to *2; keep only quota
                            # but ordered_ids already contains affinity ids at start; we need to enforce
                            if len(ordered_ids) > affinity_quota:
                                # keep first affinity_quota, stash excess for later? just keep quota for now
                                # excess will be considered as part of merged list; we keep them but quota logic later handles
                                pass
                # fallback personal genre affinity if similar users gave few results
                if len([bid for bid in ordered_ids if bid not in seen]) < affinity_quota:  # keep simple
                    pass
                # direct personal genre match fallback
                if len(ordered_ids) < affinity_quota:
                    needed = affinity_quota - len(ordered_ids)
                    # books sharing profile genres/authors, most recent
                    conds = []
                    if profile_genre_ids:
                        conds.append(
                            exists().where(
                                (book_genres.c.book_id == Book.id)
                                & (book_genres.c.genre_id.in_(list(profile_genre_ids)))
                            )
                        )
                    if profile_author_ids:
                        conds.append(
                            exists().where(
                                (book_authors.c.book_id == Book.id)
                                & (book_authors.c.author_id.in_(list(profile_author_ids)))
                            )
                        )
                    if conds:
                        from sqlalchemy import or_ as sa_or

                        q = select(Book).options(selectinload(Book.genres), selectinload(Book.authors)).where(Book.id != book_id, Book.is_active.is_(True))
                        q = _visible_filter(q)
                        q = q.where(sa_or(*conds)).order_by(Book.created_at.desc()).limit(needed * 2)
                        cand_books = (await session.scalars(q)).all()
                        for b in cand_books:
                            if b.id not in seen:
                                ordered_ids.append(b.id)
                                seen.add(b.id)
                                if len([x for x in ordered_ids]) >= affinity_quota:
                                    break
    except Exception:
        # affinity is best-effort, ignore errors
        pass

    # ensure affinity quota slice: keep first affinity_quota from ordered_ids
    # but we already appended affinity candidates first, so they are at front
    # Next layers append after

    # --- 2) Contexto do livro atual (~30%) ---
    if target_genre_ids or target_author_ids:
        from sqlalchemy import or_ as sa_or

        conds = []
        if target_genre_ids:
            conds.append(
                exists().where(
                    (book_genres.c.book_id == Book.id)
                    & (book_genres.c.genre_id.in_(target_genre_ids))
                )
            )
        if target_author_ids:
            conds.append(
                exists().where(
                    (book_authors.c.book_id == Book.id)
                    & (book_authors.c.author_id.in_(target_author_ids))
                )
            )
        q = select(Book).options(selectinload(Book.genres), selectinload(Book.authors)).where(Book.id != book_id, Book.is_active.is_(True))
        q = _visible_filter(q)
        q = q.where(sa_or(*conds)).order_by(Book.created_at.desc()).limit(context_quota * 3)
        ctx_books = (await session.scalars(q)).all()
        # prioritize books matching both genre and author

        def _score(b: Book) -> int:
            s = 0
            if target_genre_ids and any(g.id in target_genre_ids for g in (b.genres or [])):
                s += 1
            if target_author_ids and any(a.id in target_author_ids for a in (b.authors or [])):
                s += 2
            return s
        ctx_books.sort(key=_score, reverse=True)
        for b in ctx_books:
            if b.id not in seen:
                ordered_ids.append(b.id)
                seen.add(b.id)
                # we limit adding to context_quota, but allow overflow for dedup later
                if len([x for x in ordered_ids]) >= affinity_quota + context_quota:
                    break

    # --- 3) Tendências globais inter-escolas (~20%) ---
    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        trends_rows = await session.execute(
            select(BookCopy.book_id, func.count(Loan.id).label('cnt'))
            .join(Loan, Loan.copy_id == BookCopy.id)
            .where(Loan.borrowed_at >= since)
            .group_by(BookCopy.book_id)
            .order_by(func.count(Loan.id).desc())
            .limit(trends_quota * 3)
        )
        for bid, _ in trends_rows.all():
            if bid is None or bid == book_id or bid in seen:
                continue
            # visibility check
            vis = await session.scalar(
                _visible_filter(select(Book).where(Book.id == bid, Book.is_active.is_(True)))
            )
            if vis is None:
                continue
            ordered_ids.append(bid)
            seen.add(bid)
            if len(ordered_ids) >= affinity_quota + context_quota + trends_quota:
                break
    except Exception:
        pass

    # --- Fallback Lazy Direcionado: mesmo gênero ou mesmo autor ---
    if len(ordered_ids) < limit and (target_genre_ids or target_author_ids):
        needed = limit - len(ordered_ids)
        from sqlalchemy import or_ as sa_or

        conds = []
        if target_genre_ids:
            conds.append(
                exists().where(
                    (book_genres.c.book_id == Book.id)
                    & (book_genres.c.genre_id.in_(target_genre_ids))
                )
            )
        if target_author_ids:
            conds.append(
                exists().where(
                    (book_authors.c.book_id == Book.id)
                    & (book_authors.c.author_id.in_(target_author_ids))
                )
            )
        q = select(Book).options(selectinload(Book.genres), selectinload(Book.authors)).where(Book.id != book_id, Book.is_active.is_(True))
        q = _visible_filter(q)
        if ordered_ids:
            q = q.where(Book.id.notin_(ordered_ids))
        q = q.where(sa_or(*conds)).order_by(Book.created_at.desc()).limit(needed)
        fallback = (await session.scalars(q)).all()
        for b in fallback:
            if b.id not in seen:
                ordered_ids.append(b.id)
                seen.add(b.id)
    # se ainda vazio, retorna [] — não força com livros aleatórios

    # trim to limit, preserving pipeline order
    ordered_ids = ordered_ids[:limit]

    if not ordered_ids:
        return []

    # fetch books in order, preserve ordered_ids order
    books_map = {
        b.id: b
        for b in (await session.scalars(select(Book).options(selectinload(Book.genres), selectinload(Book.authors)).where(Book.id.in_(ordered_ids)))).all()
    }
    books_ordered = [books_map[bid] for bid in ordered_ids if bid in books_map]

    # diversificação: evita >2 mesmo autor seguidos
    books_ordered = _diversify_books(books_ordered)

    # build response with derived_state and counts
    book_ids = [b.id for b in books_ordered]
    derived_list = await _derived_states(session, book_ids, school_scope)
    total_map, avail_map = await _copies_counts(session, book_ids, school_scope)
    result = [
        {
            **_book_public(b),
            'derived_state': st,
            'total_copies': total_map.get(b.id, 0),
            'available_copies': avail_map.get(b.id, 0),
        }
        for b, st in zip(books_ordered, derived_list)
    ]
    return result


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

    # Tenant isolation: permite livro órfão (0 cópias) para qualquer escola; se tem cópias, precisa ter na escola do usuário  # noqa: E501
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot access books',
            )
        has_any_copy = await session.scalar(
            select(BookCopy.id).where(BookCopy.book_id == book.id).limit(1)
        )
        if has_any_copy is not None:
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
    total_map, avail_map = await _copies_counts(session, [book.id], school_scope)  # noqa: E501
    return {
        **_book_public(book),
        'derived_state': derived,
        'total_copies': total_map.get(book.id, 0),
        'available_copies': avail_map.get(book.id, 0),
    }


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

    data = book.model_dump(exclude_unset=True)
    genre_ids = data.pop('genre_ids', None)
    genre_names = data.pop('genre_names', None)
    author_ids = data.pop('author_ids', None)
    author_names = data.pop('author_names', None)
    for key, value in data.items():
        setattr(db_book, key, value)

    # handle genres update if provided
    if genre_ids is not None or genre_names is not None:
        if genre_ids == [] and genre_names in (None, []):
            db_book.genres = []
        else:
            new_genres = await _resolve_genres_for_book(
                session, genre_ids, genre_names
            )
            db_book.genres = new_genres

    # handle authors update if provided
    if author_ids is not None or author_names is not None:
        if author_ids == [] and author_names in (None, []):
            db_book.authors = []
        else:
            new_authors = await _resolve_authors_for_book(
                session, author_ids, author_names
            )
            db_book.authors = new_authors

    db_book.edited_by = user.id
    session.add(db_book)
    await session.commit()
    await session.refresh(db_book)

    # ensure genres/authors loaded for response
    await session.refresh(db_book, attribute_names=['genres', 'authors'])
    derived = (
        await _derived_states(
            session,
            [db_book.id],
            None if user.role == UserRole.SUPER_ADMIN else user.school_id,
        )
    )[0]
    total_map, avail_map = await _copies_counts(
        session, [db_book.id], None if user.role == UserRole.SUPER_ADMIN else user.school_id  # noqa: E501
    )
    return {
        **_book_public(db_book),
        'derived_state': derived,
        'total_copies': total_map.get(db_book.id, 0),
        'available_copies': avail_map.get(db_book.id, 0),
    }
