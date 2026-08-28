from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import School, User, UserRole
from src.schemas import (
    FilterPage,
    Message,
    PaginatedResponse,
    SchoolAdminCreateSchema,
    SchoolPublic,
    SchoolSchema,
    UserPublic,
)
from src.security import get_current_active_super_admin, get_password_hash
from src.utils.pagination import paginate

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


@router.get('/', response_model=PaginatedResponse[SchoolPublic])
async def list_schools(
    session: Session,
    _: SuperAdmin,
    filter_page: Annotated[FilterPage, Depends()],
):
    sttm = select(School).order_by(School.id)
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
        cpf=admin.cpf,
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
            detail='Username, Email or CPF already exists',
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
