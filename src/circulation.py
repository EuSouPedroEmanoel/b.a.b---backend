"""Central resolution and enforcement of school circulation policies."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    CirculationPolicy,
    Loan,
    LoanStatus,
    SchoolNonWorkingDay,
    User,
    UserRole,
)
from src.permissions import has_personal_reader_capability
from src.settings import Settings

WEEKEND_START = 5


@dataclass(frozen=True)
class ResolvedCirculationPolicy:
    reader_role: UserRole
    max_active_loans: int
    loan_duration_days: int
    max_renewals: int
    can_reserve: bool
    max_active_reservations: int
    block_new_loans_when_overdue: bool
    post_overdue_suspension_days: int
    count_only_business_days: bool
    move_due_date_to_next_business_day: bool = False
    apply_overdue_due_date_reduction: bool = True
    overdue_due_date_reduction_days: int = 1
    max_overdue_reductions: int = 14
    minimum_loan_days_after_penalties: int = 1
    overdue_recovery_mode: str = 'on_time_returns'
    overdue_recovery_on_time_returns: int | None = 3
    overdue_recovery_days: int | None = None


DEFAULT_POLICIES = {
    UserRole.STUDENT: ResolvedCirculationPolicy(
        reader_role=UserRole.STUDENT,
        max_active_loans=3,
        loan_duration_days=14,
        max_renewals=0,
        can_reserve=True,
        max_active_reservations=3,
        block_new_loans_when_overdue=True,
        post_overdue_suspension_days=0,
        count_only_business_days=False,
        move_due_date_to_next_business_day=False,
        apply_overdue_due_date_reduction=True,
        overdue_due_date_reduction_days=1,
        max_overdue_reductions=14,
        minimum_loan_days_after_penalties=1,
        overdue_recovery_mode='on_time_returns',
        overdue_recovery_on_time_returns=3,
        overdue_recovery_days=None,
    ),
    UserRole.TEACHER: ResolvedCirculationPolicy(
        reader_role=UserRole.TEACHER,
        max_active_loans=5,
        loan_duration_days=21,
        max_renewals=0,
        can_reserve=True,
        max_active_reservations=5,
        block_new_loans_when_overdue=True,
        post_overdue_suspension_days=0,
        count_only_business_days=False,
        move_due_date_to_next_business_day=False,
        apply_overdue_due_date_reduction=True,
        overdue_due_date_reduction_days=1,
        max_overdue_reductions=14,
        minimum_loan_days_after_penalties=1,
        overdue_recovery_mode='on_time_returns',
        overdue_recovery_on_time_returns=3,
        overdue_recovery_days=None,
    ),
}


def policy_public(
    policy: ResolvedCirculationPolicy | CirculationPolicy,
) -> dict:
    return {
        'reader_role': policy.reader_role,
        'max_active_loans': policy.max_active_loans,
        'loan_duration_days': policy.loan_duration_days,
        'max_renewals': policy.max_renewals,
        'can_reserve': policy.can_reserve,
        'max_active_reservations': policy.max_active_reservations,
        'block_new_loans_when_overdue': policy.block_new_loans_when_overdue,
        'post_overdue_suspension_days': policy.post_overdue_suspension_days,
        'count_only_business_days': policy.count_only_business_days,
        'move_due_date_to_next_business_day': (
            policy.move_due_date_to_next_business_day
        ),
        'apply_overdue_due_date_reduction': (
            policy.apply_overdue_due_date_reduction
        ),
        'overdue_due_date_reduction_days': (
            policy.overdue_due_date_reduction_days
        ),
        'max_overdue_reductions': policy.max_overdue_reductions,
        'minimum_loan_days_after_penalties': (
            policy.minimum_loan_days_after_penalties
        ),
        'overdue_recovery_mode': policy.overdue_recovery_mode,
        'overdue_recovery_on_time_returns': (
            policy.overdue_recovery_on_time_returns
        ),
        'overdue_recovery_days': policy.overdue_recovery_days,
    }


def _as_resolved(policy: CirculationPolicy) -> ResolvedCirculationPolicy:
    return ResolvedCirculationPolicy(**policy_public(policy))


async def resolve_circulation_policy(
    session: AsyncSession, school_id: int, role: UserRole
) -> ResolvedCirculationPolicy:
    """Return persisted policy, or the safe virtual default for the role."""
    if not has_personal_reader_capability(role):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Este perfil não participa da circulação pessoal.',
        )
    if not isinstance(role, UserRole):
        role = UserRole(role)
    policy = await session.scalar(
        select(CirculationPolicy).where(
            CirculationPolicy.school_id == school_id,
            CirculationPolicy.reader_role == role,
        )
    )
    return _as_resolved(policy) if policy else DEFAULT_POLICIES[role]


async def resolve_school_policies(
    session: AsyncSession, school_id: int
) -> list[ResolvedCirculationPolicy]:
    persisted = (await session.scalars(
        select(CirculationPolicy).where(
            CirculationPolicy.school_id == school_id
        )
    )).all()
    by_role = {policy.reader_role: policy for policy in persisted}
    return [
        _as_resolved(by_role[role])
        if role in by_role
        else DEFAULT_POLICIES[role]
        for role in (UserRole.STUDENT, UserRole.TEACHER)
    ]


async def calculate_due_date(
    session: AsyncSession,
    school_id: int,
    policy: ResolvedCirculationPolicy,
    penalty_days: int,
    borrowed_at: datetime | None = None,
) -> datetime:
    """Calculate a new loan due date using the school's resolved policy.

    The borrowing date never consumes a day.  Business-day calculation keeps
    the loan timestamp, but evaluates eligibility by calendar date.
    """
    start = borrowed_at or datetime.now(tz=ZoneInfo('UTC'))
    reduction = penalty_days if policy.apply_overdue_due_date_reduction else 0
    duration = max(
        Settings().LOAN_MIN_DAYS,
        policy.minimum_loan_days_after_penalties,
        policy.loan_duration_days - reduction,
    )
    if (
        not policy.count_only_business_days
        and not policy.move_due_date_to_next_business_day
    ):
        return start + timedelta(days=duration)

    non_working_days = set((await session.scalars(
        select(SchoolNonWorkingDay.date).where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date >= start.date(),
        )
    )).all())
    counted = 0
    candidate = start
    while counted < duration:
        candidate += timedelta(days=1)
        candidate_date: date = candidate.date()
        if policy.count_only_business_days and (
            candidate_date.weekday() >= WEEKEND_START
            or candidate_date in non_working_days
        ):
            continue
        if policy.move_due_date_to_next_business_day and (
            candidate_date.weekday() >= WEEKEND_START
            or candidate_date in non_working_days
        ):
            continue
        counted += 1
    return candidate


async def active_overdue_reductions(
    session: AsyncSession,
    borrower_id: int,
    policy: ResolvedCirculationPolicy,
    as_of: datetime | None = None,
) -> int:
    """Resolve progressive penalty state without deleting loan history."""
    if not policy.apply_overdue_due_date_reduction:
        return 0
    loans = (await session.scalars(
        select(Loan).where(
            Loan.user_id == borrower_id,
            Loan.status == LoanStatus.RETURNED,
            Loan.returned_at.is_not(None),
        ).order_by(Loan.returned_at)
    )).all()
    now = as_of or datetime.now(tz=ZoneInfo('UTC'))
    if policy.overdue_recovery_mode == 'elapsed_days':
        cutoff = now - timedelta(days=policy.overdue_recovery_days or 0)
        count = sum(
            1 for loan in loans
            if loan.late_days > 0
            and (
                loan.returned_at or now
            ).replace(tzinfo=ZoneInfo('UTC')) >= cutoff
        )
    else:
        count = 0
        on_time = 0
        threshold = policy.overdue_recovery_on_time_returns or 1
        for loan in loans:
            if loan.late_days > 0:
                count += 1
                on_time = 0
            else:
                on_time += 1
                if on_time >= threshold:
                    count = 0
    return (
        min(count, policy.max_overdue_reductions)
        * policy.overdue_due_date_reduction_days
    )


def _utc_now_naive() -> datetime:
    return datetime.now(tz=ZoneInfo('UTC')).replace(tzinfo=None)


async def lock_borrower(session: AsyncSession, borrower_id: int) -> User:
    borrower = await session.scalar(
        select(User).where(User.id == borrower_id).with_for_update()
    )
    if borrower is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Borrower not found'
        )
    return borrower


async def ensure_new_loan_allowed(
    session: AsyncSession,
    borrower: User,
    policy: ResolvedCirculationPolicy,
) -> None:
    """Validate limits and overdue-related restrictions for a locked reader."""
    now = _utc_now_naive()
    open_statuses = [LoanStatus.ACTIVE, LoanStatus.OVERDUE]
    active_loans = await session.scalar(
        select(func.count(Loan.id)).where(
            Loan.user_id == borrower.id,
            Loan.school_id == borrower.school_id,
            Loan.status.in_(open_statuses),
        )
    )
    if int(active_loans or 0) >= policy.max_active_loans:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Limite de empréstimos simultâneos atingido.',
        )

    overdue = await session.scalar(
        select(Loan.id).where(
            Loan.user_id == borrower.id,
            Loan.school_id == borrower.school_id,
            Loan.status.in_(open_statuses),
            Loan.due_date < now,
        ).limit(1)
    )
    if policy.block_new_loans_when_overdue and overdue is not None:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=(
                'Há empréstimo vencido. Devolva-o para realizar novo '
                'empréstimo.'
            ),
        )

    if policy.post_overdue_suspension_days == 0:
        return

    regularized_at = await session.scalar(
        select(func.max(Loan.returned_at)).where(
            Loan.user_id == borrower.id,
            Loan.school_id == borrower.school_id,
            Loan.status == LoanStatus.RETURNED,
            Loan.late_days > 0,
            Loan.returned_at.is_not(None),
        )
    )
    if regularized_at is None:
        return
    if regularized_at.tzinfo is not None:
        regularized_at = regularized_at.astimezone(ZoneInfo('UTC')).replace(
            tzinfo=None
        )
    release_at = regularized_at + timedelta(
        days=policy.post_overdue_suspension_days
    )
    if now < release_at:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=(
                'Empréstimos liberados em '
                f'{release_at.strftime("%d/%m/%Y às %H:%M")}.'
            ),
        )
