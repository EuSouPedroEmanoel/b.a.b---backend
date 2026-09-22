from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    BookCopy,
    BookCopySituationAudit,
    BooksStates,
    Loan,
    LoanStatus,
    Reservation,
    ReservationStatus,
    User,
    UserRole,
)
from src.schemas import (
    BookCopyPublic,
    BookCopyUpdate,
    CopySituationAuditPublic,
    CopySituationUpdate,
    FilterCopy,
    Message,
    PaginatedResponse,
)
from src.security import RoleChecker, get_current_user
from src.services.administrative_activity import record_activity
from src.utils.pagination import paginate

router = APIRouter(prefix='/copies', tags=['copies'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
StaffOnly = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
            UserRole.SUPER_ADMIN,
        ])
    ),
]


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


@router.get('/', response_model=PaginatedResponse[BookCopyPublic])
async def list_copies(
    session: Session,
    user: CurrentUser,
    copy_filter: Annotated[FilterCopy, Depends()],
):
    school_id = _resolve_school_filter(user, copy_filter)

    sttm = select(BookCopy).order_by(BookCopy.id)
    if school_id is not None:
        sttm = sttm.where(BookCopy.school_id == school_id)

    if copy_filter.state:
        sttm = sttm.where(BookCopy.state == copy_filter.state)
    if copy_filter.condition:
        sttm = sttm.where(BookCopy.condition == copy_filter.condition)
    if copy_filter.book_id:
        sttm = sttm.where(BookCopy.book_id == copy_filter.book_id)
    if copy_filter.internal_code:
        sttm = sttm.where(BookCopy.code == copy_filter.internal_code.strip())

    items, total, page, size, pages = await paginate(
        session, sttm, copy_filter
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


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
    user: StaffOnly,
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

    updates = copy.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(db_copy, key, value)

    db_copy.edited_by = user.id
    session.add(db_copy)
    record_activity(
        session,
        user,
        operation='updated',
        entity_type='copy',
        entity_id=db_copy.id,
        school_id=db_copy.school_id,
        summary=f'Exemplar {db_copy.code} atualizado.',
        changed_fields={'fields': list(updates)},
    )
    await session.commit()
    await session.refresh(db_copy)

    return db_copy


async def _managed_copy(
    copy_id: int, session: AsyncSession, user: User
) -> BookCopy:
    if user.role == UserRole.SUPER_ADMIN or user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Ação disponível apenas para a administração da escola.',
        )
    copy = await session.scalar(
        select(BookCopy)
        .where(BookCopy.id == copy_id, BookCopy.school_id == user.school_id)
        .with_for_update()
    )
    if copy is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, 'Copy not found.')
    return copy


async def _ensure_copy_lifecycle_is_consistent(
    session: AsyncSession, copy: BookCopy
) -> None:
    active_loan = await session.scalar(
        select(Loan.id)
        .where(
            Loan.copy_id == copy.id,
            Loan.status == LoanStatus.ACTIVE,
        )
        .limit(1)
    )
    if active_loan:
        raise HTTPException(
            HTTPStatus.CONFLICT,
            'Não é possível alterar a situação de um exemplar com '
            'empréstimo ativo.',
        )
    ready_reservation = await session.scalar(
        select(Reservation.id)
        .where(
            Reservation.copy_id == copy.id,
            Reservation.status == ReservationStatus.READY,
        )
        .limit(1)
    )
    if ready_reservation:
        raise HTTPException(
            HTTPStatus.CONFLICT,
            'Não é possível alterar a situação de um exemplar reservado '
            'para retirada.',
        )


@router.post('/{copy_id}/situation', response_model=BookCopyPublic)
async def change_copy_situation(
    copy_id: int,
    payload: CopySituationUpdate,
    session: Session,
    user: StaffOnly,
):
    copy = await _managed_copy(copy_id, session, user)
    if payload.state not in {
        BooksStates.AVAILABLE,
        BooksStates.ARCHIVED,
        BooksStates.LOST,
    }:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            'A situação administrativa deve ser arquivado, perdido ou '
            'disponível.',
        )
    if copy.state == payload.state:
        raise HTTPException(
            HTTPStatus.CONFLICT, 'O exemplar já está nessa situação.'
        )
    if copy.state == BooksStates.AVAILABLE and payload.state in {
        BooksStates.ARCHIVED, BooksStates.LOST
    }:
        await _ensure_copy_lifecycle_is_consistent(session, copy)
    elif not (
        copy.state in {BooksStates.ARCHIVED, BooksStates.LOST}
        and payload.state == BooksStates.AVAILABLE
    ):
        raise HTTPException(
            HTTPStatus.CONFLICT,
            'Transição de situação do exemplar não permitida.',
        )
    previous_state = copy.state
    copy.state = payload.state
    copy.edited_by = user.id
    audit = BookCopySituationAudit(
        copy_id=copy.id,
        previous_state=previous_state.value,
        # SQLAlchemy's dataclass initializer reserves ``new_state``.
        new_state='',
        justification=(
            payload.justification or 'Exemplar reintroduzido ao acervo.'
        ),
        actor_id=user.id,
    )
    audit.new_state = payload.state.value
    session.add_all([copy, audit])
    record_activity(
        session,
        user,
        operation=(
            'restored'
            if payload.state == BooksStates.AVAILABLE
            else payload.state.value
        ),
        entity_type='copy',
        entity_id=copy.id,
        school_id=copy.school_id,
        summary=f'Situação do exemplar {copy.code} alterada.',
        changed_fields={
            'state': {'from': previous_state.value, 'to': payload.state.value}
        },
        justification=payload.justification,
    )
    await session.commit()
    await session.refresh(copy)
    return copy


@router.get(
    '/{copy_id}/situation-audit',
    response_model=list[CopySituationAuditPublic],
)
async def read_copy_situation_audit(
    copy_id: int, session: Session, user: StaffOnly
):
    copy = await _managed_copy(copy_id, session, user)
    return list((await session.scalars(
        select(BookCopySituationAudit)
        .where(BookCopySituationAudit.copy_id == copy.id)
        .order_by(BookCopySituationAudit.created_at, BookCopySituationAudit.id)
    )).all())


@router.post('/{copy_id}/situation/undo', response_model=BookCopyPublic)
async def undo_copy_situation(
    copy_id: int,
    session: Session,
    user: StaffOnly,
):
    copy = await _managed_copy(copy_id, session, user)
    audit = await session.scalar(
        select(BookCopySituationAudit)
        .where(BookCopySituationAudit.copy_id == copy.id)
        .order_by(BookCopySituationAudit.id.desc())
        .with_for_update()
    )
    if audit is None or copy.state.value != audit.new_state:
        raise HTTPException(
            HTTPStatus.CONFLICT,
            'Esta alteração não pode mais ser desfeita porque a situação '
            'mudou novamente.',
        )
    if audit.previous_state in {
        BooksStates.ARCHIVED.value,
        BooksStates.LOST.value,
    }:
        await _ensure_copy_lifecycle_is_consistent(session, copy)
    previous_state = copy.state
    copy.state = BooksStates(audit.previous_state)
    copy.edited_by = user.id
    audit = BookCopySituationAudit(
        copy_id=copy.id,
        previous_state=previous_state.value,
        new_state='',
        justification='Desfazer alteração de situação.',
        actor_id=user.id,
    )
    audit.new_state = copy.state.value
    session.add_all([copy, audit])
    record_activity(
        session,
        user,
        operation='restored',
        entity_type='copy',
        entity_id=copy.id,
        school_id=copy.school_id,
        summary=f'Situação do exemplar {copy.code} restaurada.',
        changed_fields={
            'state': {'from': previous_state.value, 'to': copy.state.value}
        },
        justification='Desfazer alteração de situação.',
    )
    await session.commit()
    await session.refresh(copy)
    return copy


@router.delete('/{copy_id}', response_model=Message)
async def delete_copy(copy_id: int, session: Session, user: StaffOnly):
    raise HTTPException(
        status_code=HTTPStatus.METHOD_NOT_ALLOWED,
        detail=(
            'Exemplares não podem ser excluídos; use a situação '
            'administrativa.'
        ),
    )
