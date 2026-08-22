from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import User, UserRole
from scr.schemas import (
    FilterPage,
    Message,
    StaffCreateSchema,
    UserList,
    UserPublic,
)
from scr.security import (
    get_current_school_admin,
    get_current_user,
    get_password_hash,
)

router = APIRouter(prefix='/users', tags={'users'})
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SchoolAdmin = Annotated[User, Depends(get_current_school_admin)]


@router.post('/', status_code=HTTPStatus.CREATED, response_model=UserPublic)
async def create_user(
    user: StaffCreateSchema,
    session: Session,
    current_user: SchoolAdmin,
):
    # SCHOOL_ADMIN cannot choose another school; auto-assign own
    # SUPER_ADMIN must provide school_id explicitly
    if current_user.role == UserRole.SCHOOL_ADMIN:
        target_school_id = current_user.school_id
    else:  # SUPER_ADMIN
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='school_id is required for SUPER_ADMIN',
            )
        target_school_id = user.school_id

    hashed = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        password=hashed,
        role=user.role,
        school_id=target_school_id,
    )
    session.add(db_user)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username or Email already exists!!',
        )

    await session.refresh(db_user)
    return db_user


@router.get('/', status_code=HTTPStatus.OK, response_model=UserList)
async def read_users(
    current_user: CurrentUser,
    session: Session,
    filter_users: Annotated[FilterPage, Query()],
):
    sttm = select(User)
    # Tenant isolation: SCHOOL_ADMIN / LIBRARIAN / TEACHER / STUDENT
    # only see users in same school. SUPER_ADMIN sees all.
    if current_user.role != UserRole.SUPER_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot list users',
            )
        sttm = sttm.where(User.school_id == current_user.school_id)

    sttm = sttm.limit(filter_users.limit).offset(filter_users.offset)
    users = await session.scalars(sttm)
    return {'users': users.all()}


@router.get('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def read_user_by_id(
    user_id: int, session: Session, current_user: CurrentUser
):
    sttm = select(User).where(User.id == user_id)
    user_db = await session.scalar(sttm)

    if not user_db:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    # Tenant isolation for non SUPER_ADMIN
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and user_db.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    return user_db


@router.put('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def update_user(
    user_id: int,
    user: StaffCreateSchema,
    session: Session,
    current_user: CurrentUser,
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    current_user.username = user.username
    current_user.email = user.email
    current_user.password = get_password_hash(user.password)

    session.add(current_user)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username or Email already exists!!',
        )

    await session.refresh(current_user)

    return current_user


@router.delete('/{user_id}', status_code=HTTPStatus.OK, response_model=Message)
async def delete_user(
    user_id: int,
    session: Session,
    current_user: CurrentUser,
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    await session.delete(current_user)
    await session.commit()

    return {'message': 'User Deleted'}
