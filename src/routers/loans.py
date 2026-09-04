from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from src.schemas import (
    FilterLoan,
    LoanCreate,
    LoanPublic,
    PaginatedResponse,
)
from src.security import RoleChecker, get_current_user
from src.settings import Settings
from src.utils.pagination import paginate

router = APIRouter(prefix='/loans', tags=['loans'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
LibrarianOrAbove = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
            UserRole.SUPER_ADMIN,
        ])
    ),
]

settings = Settings()


async def _get_penalty_days(session: AsyncSession, borrower_id: int) -> int:
    result = await session.scalar(
        select(func.coalesce(func.sum(Loan.late_days), 0)).where(
            Loan.user_id == borrower_id,
            Loan.status == LoanStatus.RETURNED,
        )
    )
    return int(result or 0)


def _compute_due_date(penalty_days: int) -> datetime:
    loan_days = max(
        settings.LOAN_MIN_DAYS,
        settings.LOAN_DAYS_DEFAULT - penalty_days,
    )
    return datetime.now(tz=ZoneInfo('UTC')) + timedelta(days=loan_days)


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


async def _resolve_copy(
    payload: LoanCreate,
    session: AsyncSession,
    current_user: User,
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
        borrower_query = borrower_query.where(User.cpf == payload.cpf)
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
    current_user: LibrarianOrAbove,
):
    copy, school_id = await _resolve_copy(payload, session, current_user)
    if copy.state != BooksStates.AVAILABLE:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Copy is not available for loan',
        )

    borrower = await _resolve_borrower(payload, school_id, session)

    # penalty / due_date
    penalty = await _get_penalty_days(session, borrower.id)
    due_date = _compute_due_date(penalty)

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

    await session.commit()
    loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan.id)
    )
    return loan


@router.post('/{loan_id}/return', response_model=LoanPublic)
async def return_loan(
    loan_id: int,
    session: Session,
    current_user: LibrarianOrAbove,
):
    loan = await session.scalar(
        _loan_public_query().where(Loan.id == loan_id)
    )
    if not loan:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )

    # tenant check for non super admin
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and loan.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Loan not found'
        )

    if loan.status != LoanStatus.ACTIVE:
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
        select(BookCopy).where(BookCopy.id == loan.copy_id)
    )
    if copy is None:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Copy not found',
        )

    # find oldest active reservation for this book in same school
    reservation = await session.scalar(
        select(Reservation)
        .where(
            Reservation.book_id == copy.book_id,
            Reservation.school_id == loan.school_id,
            Reservation.status == ReservationStatus.ACTIVE,
        )
        .order_by(Reservation.created_at)
    )
    if reservation:
        copy.state = BooksStates.RESERVED
        reservation.status = ReservationStatus.FULFILLED
        session.add(reservation)
    else:
        copy.state = BooksStates.AVAILABLE
    session.add(copy)

    await session.commit()
    await session.refresh(loan)
    return loan


@router.get('/', response_model=PaginatedResponse[LoanPublic])
async def list_loans(
    session: Session,
    current_user: CurrentUser,
    loan_filter: Annotated[FilterLoan, Depends()],
):
    # Students/Teachers only see own loans; staff see school loans
    query = _loan_public_query()

    if current_user.role in {UserRole.STUDENT, UserRole.TEACHER}:
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

    query = query.order_by(Loan.id)
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
    query = query.order_by(Loan.id)
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
    # Students/Teachers can only see own loans
    if (
        current_user.role in {UserRole.STUDENT, UserRole.TEACHER}
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
