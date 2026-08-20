from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import User
from scr.schemas import (
    FilterPage,
    Message,
    UserList,
    UserPublic,
    UserSchema,
)
from scr.security import (
    get_current_user,
    get_password_hash,
)

router = APIRouter(prefix='/users', tags={'users'})
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post('/', status_code=HTTPStatus.CREATED, response_model=UserPublic)
async def create_user(user: UserSchema, session: Session):

    user_data = user.model_dump()
    user_data['password'] = get_password_hash(user_data['password'])
    db_user = User(**user_data)
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

    sttm = select(User).limit(filter_users.limit).offset(filter_users.offset)
    users = await session.scalars(sttm)
    return {'users': users}


@router.get('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def read_user_by_id(user_id: int, session: Session):
    sttm = select(User).where(User.id == user_id)
    user_db: UserPublic = await session.scalar(sttm)

    if not user_db:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    return user_db


@router.put('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def update_user(
    user_id: int,
    user: UserSchema,
    session: Session,
    current_user: CurrentUser,
):

    if user_id != current_user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    current_user.username = user.username
    current_user.email = user.email
    current_user.password = user.password

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
