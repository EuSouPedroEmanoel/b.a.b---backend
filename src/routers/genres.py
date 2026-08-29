from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Genre, UserRole
from src.schemas import FilterPage, GenreCreate, GenrePublic, PaginatedResponse
from src.security import RoleChecker, get_current_user
from src.utils.genres import display_name_genre, slugify_genre
from src.utils.pagination import paginate

router = APIRouter(tags=['genres'], prefix='/genres')

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[object, Depends(get_current_user)]
StaffOnly = Annotated[
    object,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
            UserRole.SUPER_ADMIN,
        ])
    ),
]


async def get_or_create_genre_by_name(  # pragma: no cover
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


async def get_or_create_genres(  # pragma: no cover
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
        genre = await get_or_create_genre_by_name(session, str(raw))
        result.append(genre)
    return result


@router.get('/', response_model=PaginatedResponse[GenrePublic])
async def list_genres(
    session: Session,
    user: CurrentUser,
    filter_page: Annotated[FilterPage, Depends()],
    q: str | None = None,
):
    sttm = select(Genre).order_by(Genre.name)
    if q and q.strip():
        raw = q.strip()
        sttm = sttm.where(
            (Genre.name.ilike(f'%{raw}%')) | (Genre.slug.ilike(f'%{raw}%'))
        )
    items, total, page, size, pages = await paginate(
        session, sttm, filter_page
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/{genre_id}', response_model=GenrePublic)
async def get_genre(genre_id: int, session: Session, user: CurrentUser):
    genre = await session.scalar(select(Genre).where(Genre.id == genre_id))
    if not genre:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Genre not found'
        )
    return genre


@router.post('/', response_model=GenrePublic, status_code=HTTPStatus.CREATED)
async def create_genre(
    payload: GenreCreate, session: Session, user: StaffOnly
):
    name = display_name_genre(payload.name)
    if not name:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail='Invalid genre name',
        )
    slug = slugify_genre(name)
    existing = await session.scalar(select(Genre).where(Genre.slug == slug))
    if existing:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Genre already exists'
        )
    genre = Genre(name=name, slug=slug)
    session.add(genre)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Genre already exists'
        )
    await session.refresh(genre)
    return genre


@router.delete('/{genre_id}', status_code=HTTPStatus.OK)  # pragma: no cover
async def delete_genre(genre_id: int, session: Session, user: StaffOnly):
    # only SUPER_ADMIN

    # user is already checked StaffOnly but we need SUPER_ADMIN
    current = user  # type: ignore
    if getattr(current, 'role', None) != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )
    genre = await session.scalar(select(Genre).where(Genre.id == genre_id))
    if not genre:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Genre not found'
        )
    await session.delete(genre)
    await session.commit()
    return {'message': 'Genre deleted'}
