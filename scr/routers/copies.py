from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import BookCopy, User, UserRole
from scr.schemas import (
    BookCopyList,
    BookCopyPublic,
    BookCopyUpdate,
    FilterCopy,
    Message,
)
from scr.security import get_current_user

router = APIRouter(prefix='/copies', tags=['copies'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _resolve_school_filter(user: User, copy_filter: FilterCopy) -> int | None:
    if user.role == UserRole.SUPER_ADMIN:
        return copy_filter.school_id
    # school-scoped roles: enforce own school
    if user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User without school cannot access copies',
        )
    return user.school_id


@router.get('/', response_model=BookCopyList)
async def list_copies(
    session: Session,
    user: CurrentUser,
    copy_filter: Annotated[FilterCopy, Depends()],
):
    school_id = _resolve_school_filter(user, copy_filter)

    sttm = select(BookCopy)
    if school_id is not None:
        sttm = sttm.where(BookCopy.school_id == school_id)

    if copy_filter.state:
        sttm = sttm.where(BookCopy.state == copy_filter.state)
    if copy_filter.condition:
        sttm = sttm.where(BookCopy.condition == copy_filter.condition)

    copies = await session.scalars(
        sttm.limit(copy_filter.limit).offset(copy_filter.offset)
    )

    return {'copies': copies.all()}


@router.get('/{copy_id}', response_model=BookCopyPublic)
async def read_copy_by_id(copy_id: int, session: Session, user: CurrentUser):
    school_id = _resolve_school_filter(user, FilterCopy())

    sttm = select(BookCopy).where(BookCopy.id == copy_id)
    if school_id is not None:
        sttm = sttm.where(BookCopy.school_id == school_id)

    copy_db = await session.scalar(sttm)

    if not copy_db:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Copy not found.'
        )

    return copy_db


@router.patch('/{copy_id}', response_model=BookCopyPublic)
async def patch_copy(
    copy_id: int,
    session: Session,
    user: CurrentUser,
    copy: BookCopyUpdate,
):
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='SUPER_ADMIN cannot patch copies directly',
        )
    if user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User without school cannot patch copies',
        )

    db_copy = await session.scalar(
        select(BookCopy).where(
            BookCopy.school_id == user.school_id, BookCopy.id == copy_id
        )
    )

    if not db_copy:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Copy not found.'
        )

    for key, value in copy.model_dump(exclude_unset=True).items():
        setattr(db_copy, key, value)

    session.add(db_copy)
    await session.commit()
    await session.refresh(db_copy)

    return db_copy


@router.delete('/{copy_id}', response_model=Message)
async def delete_copy(copy_id: int, session: Session, user: CurrentUser):
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='SUPER_ADMIN cannot delete copies directly',
        )
    if user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User without school cannot delete copies',
        )

    copy_db = await session.scalar(
        select(BookCopy).where(
            BookCopy.school_id == user.school_id, BookCopy.id == copy_id
        )
    )

    if not copy_db:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Copy not found.'
        )

    await session.delete(copy_db)
    await session.commit()

    return {'message': 'Copy has been deleted successfully.'}
