from calendar import monthrange
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AccountActivationAttempt,
    AdministrativeActivity,
    Loan,
    LoanStatus,
    PasswordResetUndo,
    PrivacyRequest,
    PrivacyRequestStatus,
    Reservation,
    ReservationStatus,
    RevokedToken,
    User,
    UserSituationAudit,
)
from src.services.privacy import active_loans, anonymize_user


def _months_before(value: datetime, months: int) -> datetime:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def run_privacy_retention(
    session: AsyncSession, now: datetime | None = None
) -> dict[str, int]:
    """Apply fixed retention rules and return non-sensitive metrics."""
    now = now or datetime.utcnow()
    metrics = {
        'accounts_anonymized': 0,
        'loans_anonymized': 0,
        'reservations_removed': 0,
        'requests_anonymized': 0,
        'audits_removed': 0,
        'attempts_removed': 0,
        'tokens_removed': 0,
    }

    disabled_cutoff = _months_before(now, 6)
    disabled_users = list(
        (
            await session.scalars(
                select(User)
                .where(
                    User.is_active.is_(False),
                    User.deactivated_at.is_not(None),
                    User.deactivated_at < disabled_cutoff,
                )
                .with_for_update()
            )
        ).all()
    )
    for user in disabled_users:
        if user.username.startswith('anonymized-'):
            continue
        if await active_loans(session, user.id):
            continue
        await anonymize_user(session, user)
        await session.execute(
            update(Loan)
            .where(Loan.user_id == user.id, Loan.status != LoanStatus.ACTIVE)
            .values(user_id=None)
        )
        metrics['accounts_anonymized'] += 1

    year_cutoff = datetime(now.year, 1, 1)
    result = await session.execute(
        update(Loan)
        .where(
            Loan.user_id.is_not(None),
            Loan.status != LoanStatus.ACTIVE,
            Loan.returned_at.is_not(None),
            Loan.returned_at < year_cutoff,
        )
        .values(user_id=None)
    )
    metrics['loans_anonymized'] = result.rowcount or 0

    cancelled = await session.execute(
        delete(Reservation).where(
            Reservation.status == ReservationStatus.CANCELLED
        )
    )
    metrics['reservations_removed'] = cancelled.rowcount or 0

    request_cutoff = now - timedelta(days=720)
    request_result = await session.execute(
        update(PrivacyRequest)
        .where(
            PrivacyRequest.status.in_([
                PrivacyRequestStatus.FULFILLED,
                PrivacyRequestStatus.PARTIALLY_FULFILLED,
                PrivacyRequestStatus.DENIED,
                PrivacyRequestStatus.CANCELLED,
            ]),
            PrivacyRequest.updated_at < request_cutoff,
        )
        .values(
            user_id=None,
            description=None,
            resolution=None,
            decided_by=None,
        )
    )
    metrics['requests_anonymized'] = request_result.rowcount or 0

    audit_cutoff = now - timedelta(days=365)
    audit_result = await session.execute(
        delete(AdministrativeActivity).where(
            AdministrativeActivity.occurred_at < audit_cutoff
        )
    )
    await session.execute(
        delete(UserSituationAudit).where(
            UserSituationAudit.created_at < audit_cutoff
        )
    )
    metrics['audits_removed'] = audit_result.rowcount or 0

    attempts = await session.execute(
        delete(AccountActivationAttempt).where(
            AccountActivationAttempt.created_at
            < now - timedelta(days=90)
        )
    )
    metrics['attempts_removed'] = attempts.rowcount or 0

    tokens = await session.execute(
        delete(RevokedToken).where(RevokedToken.expires_at < now)
    )
    metrics['tokens_removed'] = tokens.rowcount or 0

    await session.execute(
        delete(PasswordResetUndo).where(
            PasswordResetUndo.expires_at < now
        )
    )
    await session.commit()
    return metrics
