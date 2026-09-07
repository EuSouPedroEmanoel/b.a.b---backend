from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.circulation import (
    active_overdue_reductions,
    resolve_circulation_policy,
)
from src.models import BookCopy, BooksStates, Loan, LoanStatus, UserRole


def _loan(
    *, user_id: int, school_id: int, copy_id: int,
    returned_at: datetime, late_days: int
):
    return Loan(
        copy_id=copy_id,
        user_id=user_id,
        school_id=school_id,
        due_date=returned_at - timedelta(days=1),
        returned_at=returned_at,
        late_days=late_days,
        status=LoanStatus.RETURNED,
    )


@pytest.mark.asyncio
async def test_progressive_penalty_recovers_after_on_time_returns(
    session, school, student, book
):
    copy = BookCopy(
        book_id=book.id, school_id=school.id, added_by=student.id,
        code='PENALTY-1', state=BooksStates.AVAILABLE,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    start = datetime(2026, 1, 1, tzinfo=ZoneInfo('UTC'))
    session.add_all([
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=start, late_days=2),
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=start + timedelta(days=1), late_days=0),
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=start + timedelta(days=2), late_days=0),
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=start + timedelta(days=3), late_days=0),
    ])
    await session.commit()
    policy = await resolve_circulation_policy(session, school.id, UserRole.STUDENT)
    assert await active_overdue_reductions(
        session, student.id, policy, start + timedelta(days=4)
    ) == 0


@pytest.mark.asyncio
async def test_progressive_penalty_is_capped_and_elapsed_recovery_resets(
    session, school, student, book
):
    copy = BookCopy(
        book_id=book.id, school_id=school.id, added_by=student.id,
        code='PENALTY-2', state=BooksStates.AVAILABLE,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    now = datetime(2026, 2, 20, tzinfo=ZoneInfo('UTC'))
    session.add_all([
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=now - timedelta(days=10), late_days=1),
        _loan(user_id=student.id, school_id=school.id, copy_id=copy.id,
              returned_at=now - timedelta(days=5), late_days=1),
    ])
    await session.commit()
    policy = await resolve_circulation_policy(session, school.id, UserRole.STUDENT)
    policy = replace(
        policy,
        overdue_recovery_mode='elapsed_days',
        overdue_recovery_days=30,
        max_overdue_reductions=1,
        overdue_due_date_reduction_days=2,
    )
    assert await active_overdue_reductions(
        session, student.id, policy, now
    ) == 2
    assert await active_overdue_reductions(
        session, student.id, policy, now + timedelta(days=31)
    ) == 0
