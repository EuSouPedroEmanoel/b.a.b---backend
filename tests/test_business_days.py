from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.circulation import ResolvedCirculationPolicy, calculate_due_date
from src.models import SchoolNonWorkingDay, UserRole


def _policy(*, business_days: bool, duration: int = 3):
    return ResolvedCirculationPolicy(
        reader_role=UserRole.STUDENT,
        max_active_loans=3,
        loan_duration_days=duration,
        max_renewals=0,
        can_reserve=True,
        max_active_reservations=3,
        block_new_loans_when_overdue=True,
        post_overdue_suspension_days=0,
        count_only_business_days=business_days,
    )


@pytest.mark.asyncio
async def test_business_days_start_on_day_after_loan_and_skip_weekend(
    session, school
):
    friday = datetime(2026, 6, 5, 14, 30, tzinfo=ZoneInfo('UTC'))
    due = await calculate_due_date(
        session, school.id, _policy(business_days=True, duration=1), 0, friday
    )
    assert due == datetime(2026, 6, 8, 14, 30, tzinfo=ZoneInfo('UTC'))


@pytest.mark.asyncio
async def test_business_days_skip_school_non_working_days(session, school):
    session.add(SchoolNonWorkingDay(
        school_id=school.id, date=datetime(2026, 6, 9).date(),
    ))
    await session.commit()
    monday = datetime(2026, 6, 8, 9, 0, tzinfo=ZoneInfo('UTC'))
    due = await calculate_due_date(
        session, school.id, _policy(business_days=True, duration=3), 0, monday
    )
    assert due == datetime(2026, 6, 12, 9, 0, tzinfo=ZoneInfo('UTC'))


@pytest.mark.asyncio
async def test_calendar_day_policy_preserves_current_duration(session, school):
    friday = datetime(2026, 6, 5, 14, 30, tzinfo=ZoneInfo('UTC'))
    due = await calculate_due_date(
        session, school.id, _policy(business_days=False, duration=1), 0, friday
    )
    assert due == datetime(2026, 6, 6, 14, 30, tzinfo=ZoneInfo('UTC'))


@pytest.mark.asyncio
async def test_business_day_policy_uses_effective_duration_after_penalty(
    session, school
):
    monday = datetime(2026, 6, 8, 9, 0, tzinfo=ZoneInfo('UTC'))
    due = await calculate_due_date(
        session, school.id, _policy(business_days=True, duration=5), 3, monday
    )
    assert due == datetime(2026, 6, 10, 9, 0, tzinfo=ZoneInfo('UTC'))
