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
    SchoolSettingsUpdate,
    SchoolSituationUpdate,
    UserCreationPublic,
    UserPublic,
)
from src.security import get_current_active_super_admin, get_current_user
from src.services.account_activation import (
    first_access_url,
    generate_invitation,
)
from src.services.administrative_activity import record_activity
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
CurrentUser = Annotated[User, Depends(get_current_user)]
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
        await session.flush()
        record_activity(
            session,
            _,
            operation='created',
            entity_type='school',
            entity_id=db_school.id,
            school_id=db_school.id,
            summary=f'Escola {db_school.name} cadastrada.',
        )
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
        school_identifier=admin.school_identifier or admin.username,
        name=admin.name or admin.username,
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


def _can_manage_school_settings(current_user: User, school_id: int) -> bool:
    return current_user.role == UserRole.SUPER_ADMIN or (
        current_user.role in {UserRole.SCHOOL_ADMIN, UserRole.LIBRARIAN}
        and current_user.school_id == school_id
    )


@router.get('/{school_id}/settings', response_model=SchoolPublic)
async def get_school_settings(
    school_id: int,
    session: Session,
    current_user: CurrentUser,
):
    if current_user.role not in {
        UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.LIBRARIAN
    } or not _can_manage_school_settings(current_user, school_id):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN)
    school = await session.scalar(select(School).where(School.id == school_id))
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    return school


@router.patch('/{school_id}/settings', response_model=SchoolPublic)
async def update_school_settings(
    school_id: int,
    settings_update: SchoolSettingsUpdate,
    session: Session,
    current_user: CurrentUser,
):
    if not _can_manage_school_settings(current_user, school_id):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN)
    school = await session.scalar(select(School).where(School.id == school_id))
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    school.allow_student_condition_filter = (
        settings_update.allow_student_condition_filter
    )
    school.allow_student_restricted_availability = (
        settings_update.allow_student_restricted_availability
    )
    record_activity(
        session,
        current_user,
        operation='updated',
        entity_type='school',
        entity_id=school.id,
        school_id=school.id,
        summary=f'Preferências da escola {school.name} alteradas.',
        changed_fields={
            'allow_student_condition_filter': (
                settings_update.allow_student_condition_filter
            ),
            'allow_student_restricted_availability': (
                settings_update.allow_student_restricted_availability
            ),
        },
    )
    await session.commit()
    await session.refresh(school)
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
    if not school.is_active:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='School is inactive'
        )
    school.is_active = False
    session.add(school)
    record_activity(
        session,
        _,
        operation='deactivated',
        entity_type='school',
        entity_id=school.id,
        school_id=school.id,
        summary=f'Escola {school.name} desativada.',
    )
    await session.commit()
    return {'message': 'School deactivated'}


@router.post('/{school_id}/situation', response_model=SchoolPublic)
async def change_school_situation(
    school_id: int,
    payload: SchoolSituationUpdate,
    session: Session,
    _: SuperAdmin,
):
    school = await session.scalar(
        select(School).where(School.id == school_id).with_for_update()
    )
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    if school.is_active == payload.is_active:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='School is already in this situation',
        )
    school.is_active = payload.is_active
    session.add(school)
    record_activity(
        session,
        _,
        operation='activated' if payload.is_active else 'deactivated',
        entity_type='school',
        entity_id=school.id,
        school_id=school.id,
        summary=(
            f'Escola {school.name} '
            + ('ativada.' if payload.is_active else 'desativada.')
        ),
    )
    await session.commit()
    await session.refresh(school)
    return school
