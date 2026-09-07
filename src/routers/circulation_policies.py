from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.circulation import policy_public, resolve_school_policies
from src.database import get_session
from src.models import (
    AdministrativeCapability,
    CirculationPolicy,
    School,
    User,
    UserRole,
)
from src.permissions import has_administrative_capability
from src.schemas import CirculationPoliciesPublic, CirculationPoliciesUpdate
from src.security import get_current_user

router = APIRouter(
    prefix='/circulation-policies', tags=['circulation-policies']
)

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _authorize_school(
    school_id: int, session: AsyncSession, current_user: User
) -> School:
    school = await session.scalar(select(School).where(School.id == school_id))
    if school is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and current_user.school_id != school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Você não pode administrar regras de outra escola.',
        )
    return school


def _can_view(current_user: User, school_id: int) -> bool:
    return current_user.role == UserRole.SUPER_ADMIN or (
        current_user.school_id == school_id
        and current_user.role in {UserRole.SCHOOL_ADMIN, UserRole.LIBRARIAN}
    )


def _can_manage(current_user: User, school_id: int) -> bool:
    return (
        (
            current_user.role == UserRole.SCHOOL_ADMIN
            and current_user.school_id == school_id
        )
        or has_administrative_capability(
            current_user,
            AdministrativeCapability.MANAGE_CIRCULATION_RULES,
            school_id,
        )
    )


@router.get('/{school_id}', response_model=CirculationPoliciesPublic)
async def get_circulation_policies(
    school_id: int, session: Session, current_user: CurrentUser
):
    await _authorize_school(school_id, session, current_user)
    if not _can_view(current_user, school_id):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Você não pode consultar regras desta escola.',
        )
    policies = await resolve_school_policies(session, school_id)
    return {'policies': [policy_public(policy) for policy in policies]}


@router.put('/{school_id}', response_model=CirculationPoliciesPublic)
async def update_circulation_policies(
    school_id: int,
    payload: CirculationPoliciesUpdate,
    session: Session,
    current_user: CurrentUser,
):
    await _authorize_school(school_id, session, current_user)
    if not _can_manage(current_user, school_id):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Você não pode alterar regras desta escola.',
        )
    existing = (await session.scalars(
        select(CirculationPolicy).where(
            CirculationPolicy.school_id == school_id
        )
    )).all()
    by_role = {policy.reader_role: policy for policy in existing}

    for update in payload.policies:
        policy = by_role.get(update.reader_role)
        values = update.model_dump()
        if policy is None:
            policy = CirculationPolicy(school_id=school_id, **values)
            session.add(policy)
            continue
        for field, value in values.items():
            setattr(policy, field, value)
        session.add(policy)

    await session.commit()
    policies = await resolve_school_policies(session, school_id)
    return {'policies': [policy_public(policy) for policy in policies]}
