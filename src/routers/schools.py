from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import AccountStatus, School, User, UserRole
from src.schemas import (
    FilterPage,
    Message,
    PaginatedResponse,
    SchoolAdminCreateSchema,
    SchoolPublic,
    SchoolSchema,
    UserCreationPublic,
    UserPublic,
)
from src.security import get_current_active_super_admin
from src.services.account_activation import (
    first_access_url,
    generate_invitation,
)
from src.settings import Settings
from src.utils.cpf import (
    classify_cpf_candidates,
    cpf_storage_values,
    log_cpf_lookup_collision,
)
from src.utils.pagination import paginate

router = APIRouter(prefix='/schools', tags=['schools'])

Session = Annotated[AsyncSession, Depends(get_session)]
SuperAdmin = Annotated[User, Depends(get_current_active_super_admin)]
settings = Settings()


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
    response_model=UserCreationPublic,
)
async def create_school_admin(
    school_id: int,
    admin: SchoolAdminCreateSchema,
    session: Session,
    current_user: SuperAdmin,
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

    lookup_hash, collision_guard, last2 = cpf_storage_values(admin.cpf)
    candidates = list((await session.execute(
        select(User.id, User.cpf_collision_guard).where(
            User.cpf_lookup_hash == lookup_hash
        )
    )).all())
    duplicate, collision_ids = classify_cpf_candidates(
        candidates, collision_guard
    )
    if collision_ids:
        log_cpf_lookup_collision(
            school_id=school.id, existing_user_ids=collision_ids
        )
    if duplicate:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists',
        )
    db_user = User(
        username=admin.username,
        name=admin.name or admin.username,
        email=admin.email,
        cpf_lookup_hash=lookup_hash,
        cpf_collision_guard=collision_guard,
        cpf_last2=last2,
        password=None,
        role=UserRole.SCHOOL_ADMIN,
        school_id=school.id,
        account_status=AccountStatus.PENDING_ACTIVATION,
    )
    session.add(db_user)
    try:
        await session.flush()
        invitation, code = await generate_invitation(
            session, db_user, current_user.id
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists',
        )
    await session.refresh(db_user)
    return {
        **UserPublic.model_validate(db_user).model_dump(),
        'activation_invitation': {
            'code': code,
            'expires_at': invitation.expires_at,
            'first_access_url': first_access_url(db_user.username, code),
            'print_url': f'/users/{db_user.id}/activation/print',
        },
    }


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
