from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Author, UserRole
from src.schemas import (
    AuthorCreate,
    AuthorPublic,
    FilterPage,
    PaginatedResponse,
)
from src.security import RoleChecker, get_current_user
from src.utils.authors import display_name_author, slugify_author
from src.utils.pagination import paginate

router = APIRouter(tags=['authors'], prefix='/authors')

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


async def get_or_create_author_by_name(  # pragma: no cover
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


async def get_or_create_authors(  # pragma: no cover
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
        author = await get_or_create_author_by_name(session, str(raw))
        result.append(author)
    return result


@router.get('/', response_model=PaginatedResponse[AuthorPublic])
async def list_authors(
    session: Session,
    user: CurrentUser,
    filter_page: Annotated[FilterPage, Depends()],
    q: str | None = None,
):
    sttm = select(Author).order_by(Author.name)
    if q and q.strip():
        raw = q.strip()
        sttm = sttm.where(
            (Author.name.ilike(f'%{raw}%')) | (Author.slug.ilike(f'%{raw}%'))
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


@router.get('/{author_id}', response_model=AuthorPublic)
async def get_author(author_id: int, session: Session, user: CurrentUser):
    author = await session.scalar(select(Author).where(Author.id == author_id))
    if not author:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Author not found'
        )
    return author


@router.post('/', response_model=AuthorPublic, status_code=HTTPStatus.CREATED)
async def create_author(
    payload: AuthorCreate, session: Session, user: StaffOnly
):
    name = display_name_author(payload.name)
    if not name:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail='Invalid author name',
        )
    slug = slugify_author(name)
    existing = await session.scalar(select(Author).where(Author.slug == slug))
    if existing:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Author already exists'
        )
    author = Author(name=name, slug=slug)
    session.add(author)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Author already exists'
        )
    await session.refresh(author)
    return author


@router.delete('/{author_id}', status_code=HTTPStatus.OK)  # pragma: no cover
async def delete_author(author_id: int, session: Session, user: StaffOnly):
    current = user  # type: ignore
    if getattr(current, 'role', None) != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )
    author = await session.scalar(select(Author).where(Author.id == author_id))
    if not author:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Author not found'
        )
    await session.delete(author)
    await session.commit()
    return {'message': 'Author deleted'}
