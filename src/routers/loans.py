from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.circulation import (
    active_overdue_reductions,
    calculate_due_date,
    ensure_new_loan_allowed,
    lock_borrower,
    resolve_circulation_policy,
)
from src.database import get_session
from src.models import (
    BookCopy,
    BooksStates,
    Loan,
    LoanStatus,
    Reservation,
    ReservationStatus,
    User,
    UserRole,
)
from src.permissions import has_personal_reader_capability
from src.schemas import (
    FilterLoan,
    LoanCreate,
    LoanPublic,
    PaginatedResponse,
)
from src.security import RoleChecker, get_current_user
from src.utils.cpf import cpf_collision_guard, cpf_lookup_digest
from src.utils.pagination import paginate
from src.utils.reservation_queue import (
    lock_book_queue,
    promote_copy_to_next_reservation,
)

router = APIRouter(prefix='/loans', tags=['loans'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
LoanOperator = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
        ])
    ),
]


def _apply_situation_filter(query, situation):
    if not situation:
        return query

    open_statuses = [LoanStatus.ACTIVE, LoanStatus.OVERDUE]
    query = query.where(Loan.status.in_(open_statuses))
    if situation == 'borrowed':
        return query

    # The database stores UTC timestamps without timezone information.
    today = datetime.now(tz=ZoneInfo('UTC')).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    if situation == 'overdue':
        return query.where(Loan.due_date < today)

    return query.where(
        Loan.due_date >= today,
        Loan.due_date < today + timedelta(days=4),
    )


def _loan_public_query():
    return select(Loan).options(
        selectinload(Loan.copy).selectinload(BookCopy.book),
        selectinload(Loan.borrower),
    )


async def _resolve_copy(  # noqa: PLR0912
    payload: LoanCreate,
    session: AsyncSession,
    current_user: User,
    for_update: bool = False,
) -> tuple[BookCopy, int]:
    if payload.internal_code is not None:
        copy_query = select(BookCopy).where(
            BookCopy.code == payload.internal_code
        )
        if current_user.role == UserRole.SUPER_ADMIN:
            if payload.school_id is not None:
                copy_query = copy_query.where(
                    BookCopy.school_id == payload.school_id
                )
        else:
            if current_user.school_id is None:
                raise HTTPException(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail='User without school cannot create loans',
                )
            copy_query = copy_query.where(
                BookCopy.school_id == current_user.school_id
            )
        if for_update:
            # The copy may already be present in this session's identity map
            # from the initial lookup.  Refresh it after waiting for the row
            # lock so a concurrent loan cannot make us use stale AVAILABLE
            # state.
            copy_query = copy_query.with_for_update().execution_options(
                populate_existing=True
            )
        copies = list((await session.scalars(copy_query)).all())
        if len(copies) > 1:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='Internal code is ambiguous across schools',
            )
        copy = copies[0] if copies else None
        if copy is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail='Copy not found'
            )
        return copy, copy.school_id

    if current_user.role == UserRole.SUPER_ADMIN:
        copy_query = select(BookCopy).where(BookCopy.id == payload.copy_id)
        school_id = None
    else:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot create loans',
            )
        school_id = current_user.school_id
        copy_query = select(BookCopy).where(
            BookCopy.id == payload.copy_id,
            BookCopy.school_id == school_id,
        )
    if for_update:
        # Refresh an identity-mapped copy after acquiring its row lock.
        copy_query = copy_query.with_for_update().execution_options(
            populate_existing=True
        )
    copy = await session.scalar(copy_query)
    if copy is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Copy not found'
        )
    return copy, copy.school_id


async def _resolve_borrower(
    payload: LoanCreate,
    school_id: int,
    session: AsyncSession,
) -> User:
    borrower_query = select(User)
    if payload.cpf is not None:
        borrower_query = borrower_query.where(
            User.cpf_lookup_hash == cpf_lookup_digest(payload.cpf),
            User.cpf_collision_guard == cpf_collision_guard(payload.cpf),
        )
    else:
        borrower_query = borrower_query.where(User.id == payload.user_id)
    borrower = await session.scalar(borrower_query)
    if borrower is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Borrower not found'
        )
    if not borrower.is_active:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Borrower is inactive'
        )
    if borrower.school_id != school_id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Borrower does not belong to the same school',
        )
    return borrower


@router.post('/', response_model=LoanPublic, status_code=HTTPStatus.CREATED)
async def create_loan(
    payload: LoanCreate,
    session: Session,
    current_user: LoanOperator,
):
    initial_copy, _ = await _resolve_copy(payload, session, current_user)
    await lock_book_queue(session, initial_copy.book_id)
    copy, school_id = await _resolve_copy(
        payload, session, current_user, for_update=True
    )
    reservation = None
    if payload.reservation_id is not None:
        reservation = await session.scalar(
            select(Reservation).where(
                Reservation.id == payload.reservation_id
            ).with_for_update()
        )
        if (
            reservation is None  # noqa: PLR0916
            or reservation.status != ReservationStatus.READY
            or reservation.book_id != copy.book_id
            or reservation.school_id != school_id
            or reservation.copy_id != copy.id
            or copy.state != BooksStates.RESERVED
        ):
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='Reservation is no longer available for pickup',
            )
        borrower = await _resolve_borrower(
            LoanCreate(copy_id=copy.id, user_id=reservation.user_id),
            school_id,
            session,
        )
    else:
        if copy.state != BooksStates.AVAILABLE:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail='Copy is not available for loan',
            )
        borrower = await _resolve_borrower(payload, school_id, session)

    borrower = await lock_borrower(session, borrower.id)
    policy = await resolve_circulation_policy(
        session, school_id, borrower.role
    )
    await ensure_new_loan_allowed(session, borrower, policy)

    # The historic late-return penalty is preserved, using the school's
    # configured duration as its base instead of a global fixed duration.
    penalty = await active_overdue_reductions(session, borrower.id, policy)
    due_date = await calculate_due_date(
        session, school_id, policy, penalty
    )

    loan = Loan(
        copy_id=copy.id,
        user_id=borrower.id,
        school_id=school_id,
        due_date=due_date,
        status=LoanStatus.ACTIVE,
    )
    session.add(loan)
    # atomic: update copy state
    copy.state = BooksStates.BORROWED
    session.add(copy)
    if reservation is not None:
        reservation.status = ReservationStatus.FULFILLED
        session.add(reservation)

    await session.commit()
    loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan.id)
    )
    return loan


@router.post('/{loan_id}/return', response_model=LoanPublic)
async def return_loan(
    loan_id: int,
    session: Session,
    current_user: LoanOperator,
):
    initial_loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan_id)
    )
    if not initial_loan:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )

    # tenant check for non super admin
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and initial_loan.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )

    await lock_book_queue(session, initial_loan.copy.book_id)
    loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan_id).with_for_update()
    )
    if loan is None or loan.status != LoanStatus.ACTIVE:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Loan is not active'
        )

    now = datetime.now(tz=ZoneInfo('UTC'))
    loan.returned_at = now

    # calculate late_days
    # ensure due_date is tz-aware (DB stores naive UTC)
    due = loan.due_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=ZoneInfo('UTC'))
    delta_days = (now.date() - due.date()).days
    loan.late_days = max(0, delta_days)
    loan.status = LoanStatus.RETURNED
    session.add(loan)

    # handle copy state: check for active reservation for same book
    copy = await session.scalar(
        select(BookCopy).where(BookCopy.id == loan.copy_id).with_for_update()
    )
    if copy is None:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Copy not found',
        )

    reservation = await promote_copy_to_next_reservation(session, copy)
    session.add(copy)

    await session.commit()
    await session.refresh(loan)
    result = await session.scalar(
        _loan_public_query().where(Loan.id == loan.id)
    )
    if reservation is not None:
        result.pickup_reservation_id = reservation.id
        result.pickup_reserver_username = reservation.reserver.username
    return result


@router.get('/', response_model=PaginatedResponse[LoanPublic])
async def list_loans(
    session: Session,
    current_user: CurrentUser,
    loan_filter: Annotated[FilterLoan, Depends()],
):
    # Leitores autenticados veem seus empréstimos; equipe vê os da escola.
    query = _loan_public_query()

    if has_personal_reader_capability(current_user.role):
        query = query.where(Loan.user_id == current_user.id)
    elif current_user.role == UserRole.SUPER_ADMIN:
        if loan_filter.user_id:
            query = query.where(Loan.user_id == loan_filter.user_id)
        if loan_filter.copy_id:
            query = query.where(Loan.copy_id == loan_filter.copy_id)
        # school_id filtering not in FilterLoan but could be added
    else:
        # LIBRARIAN / SCHOOL_ADMIN: school-scoped
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='User without school'
            )
        query = query.where(Loan.school_id == current_user.school_id)
        if loan_filter.user_id:
            query = query.where(Loan.user_id == loan_filter.user_id)
        if loan_filter.copy_id:
            query = query.where(Loan.copy_id == loan_filter.copy_id)

    if loan_filter.status:
        query = query.where(Loan.status == loan_filter.status)

    query = _apply_situation_filter(query, loan_filter.situation)

    query = query.order_by(
        case(
            (Loan.status.in_([LoanStatus.ACTIVE, LoanStatus.OVERDUE]), 0),
            else_=1,
        ),
        Loan.borrowed_at.desc(),
        Loan.id.desc(),
    )
    items, total, page, size, pages = await paginate(
        session, query, loan_filter
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/me', response_model=PaginatedResponse[LoanPublic])
async def list_my_loans(
    session: Session,
    current_user: CurrentUser,
    loan_filter: Annotated[FilterLoan, Depends()],
):
    query = _loan_public_query().where(Loan.user_id == current_user.id)
    if loan_filter.status:
        query = query.where(Loan.status == loan_filter.status)
    query = _apply_situation_filter(query, loan_filter.situation)
    query = query.order_by(
        case(
            (Loan.status.in_([LoanStatus.ACTIVE, LoanStatus.OVERDUE]), 0),
            else_=1,
        ),
        Loan.borrowed_at.desc(),
        Loan.id.desc(),
    )
    items, total, page, size, pages = await paginate(
        session, query, loan_filter
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/{loan_id}', response_model=LoanPublic)
async def get_loan(
    loan_id: int,
    session: Session,
    current_user: CurrentUser,
):
    loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan_id)
    )
    if not loan:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )
    # Leitores autenticados só podem consultar os próprios empréstimos.
    if (
        has_personal_reader_capability(current_user.role)
        and loan.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and loan.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )
    return loan
