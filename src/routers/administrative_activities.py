from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import AdministrativeActivity, User, UserRole
from src.schemas import (
    AdministrativeActivityFilter,
    AdministrativeActivityPublic,
    PaginatedResponse,
)
from src.security import get_current_user
from src.utils.pagination import paginate

router = APIRouter(
    prefix='/administrative-activities',
    tags=['administrative-activities'],
)
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get(
    '/', response_model=PaginatedResponse[AdministrativeActivityPublic]
)
async def list_administrative_activities(
    session: Session,
    current_user: CurrentUser,
    filters: Annotated[AdministrativeActivityFilter, Depends()],
):
    if current_user.role not in {UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN}:
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Not enough permissions')

    query = select(AdministrativeActivity)
    if current_user.role == UserRole.SCHOOL_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(HTTPStatus.FORBIDDEN, 'User without school')
        query = query.where(
            AdministrativeActivity.school_id == current_user.school_id
        )
    elif filters.school_id is not None:
        query = query.where(
            AdministrativeActivity.school_id == filters.school_id
        )
    if filters.actor_id is not None:
        query = query.where(
            AdministrativeActivity.actor_id == filters.actor_id
        )
    if filters.entity_type is not None:
        query = query.where(
            AdministrativeActivity.entity_type == filters.entity_type
        )
    if filters.operation is not None:
        query = query.where(
            AdministrativeActivity.operation == filters.operation
        )
    if filters.start_at is not None:
        query = query.where(
            AdministrativeActivity.occurred_at >= filters.start_at
        )
    if filters.end_at is not None:
        query = query.where(
            AdministrativeActivity.occurred_at <= filters.end_at
        )

    query = query.order_by(
        AdministrativeActivity.occurred_at.desc(),
        AdministrativeActivity.id.desc(),
    )
    items, total, page, size, pages = await paginate(
        session, query, filters
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }
