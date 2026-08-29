import re
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    Author,
    Book,
    BookCopy,
    BooksStates,
    Genre,
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
    return {**_book_public(db_book), 'derived_state': derived}


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
            else BooksStates.BORROWED
            if bid in has_available
            else BooksStates.ARCHIVED
        )
        for bid in book_ids
    ]


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

    result = [
        {**_book_public(b), 'derived_state': st}
        for b, st in zip(
            items,
            await _derived_states(
                session, [b.id for b in items], school_scope
            ),
        )
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
    return {**_book_public(db_book), 'derived_state': derived}
