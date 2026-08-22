from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import School, User, UserRole
from scr.schemas import (
    FilterPage,
    Message,
    SchoolAdminCreateSchema,
    SchoolList,
    SchoolPublic,
    SchoolSchema,
    UserPublic,
)
from scr.security import get_current_active_super_admin, get_password_hash

router = APIRouter(prefix='/schools', tags=['schools'])

Session = Annotated[AsyncSession, Depends(get_session)]
SuperAdmin = Annotated[User, Depends(get_current_active_super_admin)]


@router.post('/', status_code=HTTPStatus.CREATED, response_model=SchoolPublic)
async def create_school(
    school: SchoolSchema,
    session: Session,
    _: SuperAdmin,
):
    db_school = School(name=school.name, code=school.code)
    session.add(db_school)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='School code already exists',
        )
    await session.refresh(db_school)
    return db_school


@router.get('/', response_model=SchoolList)
async def list_schools(
    session: Session,
    _: SuperAdmin,
    filter_page: Annotated[FilterPage, Query()],
):
    sttm = select(School).limit(filter_page.limit).offset(filter_page.offset)
    schools = await session.scalars(sttm)
    return {'schools': schools.all()}


@router.post(
    '/{school_id}/admins',
    status_code=HTTPStatus.CREATED,
    response_model=UserPublic,
)
async def create_school_admin(
    school_id: int,
    admin: SchoolAdminCreateSchema,
    session: Session,
    _: SuperAdmin,
):
    school = await session.scalar(select(School).where(School.id == school_id))
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    if not school.is_active:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='School is inactive'
        )

    hashed = get_password_hash(admin.password)
    db_user = User(
        username=admin.username,
        email=admin.email,
        password=hashed,
        role=UserRole.SCHOOL_ADMIN,
        school_id=school.id,
    )
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username or Email already exists',
        )
    await session.refresh(db_user)
    return db_user


@router.get('/{school_id}', response_model=SchoolPublic)
async def get_school(
    school_id: int,
    session: Session,
    _: SuperAdmin,
):
    school = await session.scalar(select(School).where(School.id == school_id))
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    return school


@router.delete('/{school_id}', response_model=Message)
async def delete_school(
    school_id: int,
    session: Session,
    _: SuperAdmin,
):
    school = await session.scalar(select(School).where(School.id == school_id))
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    await session.delete(school)
    await session.commit()
    return {'message': 'School deleted'}
