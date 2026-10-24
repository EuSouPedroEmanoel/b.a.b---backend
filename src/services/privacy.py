from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AccountActivationToken,
    AccountStatus,
    AdministrativeActivity,
    Loan,
    LoanStatus,
    PasswordResetUndo,
    PrivacyProcessingMode,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Reservation,
    ReservationStatus,
    SchoolPrivacyPolicy,
    User,
    UserBookFavorite,
    UserReadingStatus,
)
from src.services.administrative_activity import record_activity


async def active_loans(session: AsyncSession, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(Loan.id)).where(
                Loan.user_id == user_id, Loan.status == LoanStatus.ACTIVE
            )
        )
        or 0
    )


async def anonymize_user(session: AsyncSession, target: User) -> None:
    target.name = 'Titular anonimizado'
    target.username = f'anonymized-{target.id}'
    target.cpf_lookup_hash = None
    target.cpf_collision_guard = None
    target.cpf_last2 = None
    target.birthdate = None
    target.turma_numero = None
    target.turma_letra = None
    target.password = None
    target.is_active = False
    target.auth_version += 1
    target.account_status = AccountStatus.DISABLED
    await session.execute(
        delete(PasswordResetUndo).where(PasswordResetUndo.user_id == target.id)
    )
    await session.execute(
        delete(AccountActivationToken).where(
            AccountActivationToken.user_id == target.id
        )
    )
    await session.execute(
        update(AdministrativeActivity)
        .where(AdministrativeActivity.actor_id == target.id)
        .values(actor_display_name='Titular anonimizado')
    )
    await session.execute(
        delete(UserBookFavorite).where(UserBookFavorite.user_id == target.id)
    )
    await session.execute(
        delete(UserReadingStatus).where(UserReadingStatus.user_id == target.id)
    )
    await session.execute(
        delete(Reservation).where(
            Reservation.user_id == target.id,
            Reservation.status.in_([
                ReservationStatus.ACTIVE,
                ReservationStatus.READY,
            ]),
        )
    )


async def reprocess_pending_anonymization(
    session: AsyncSession, user_id: int
) -> int:
    """Fulfill pending automatic anonymization requests when unblocked.

    The caller keeps this operation in the same transaction as the event
    that removed the operational dependency, such as a loan return.
    """
    requests = list(
        (
            await session.scalars(
                select(PrivacyRequest)
                .where(
                    PrivacyRequest.user_id == user_id,
                    PrivacyRequest.request_type
                    == PrivacyRequestType.ANONYMIZATION,
                    PrivacyRequest.status == PrivacyRequestStatus.PENDING,
                )
                .order_by(PrivacyRequest.id)
                .with_for_update()
            )
        ).all()
    )
    if not requests:
        return 0

    target = await session.scalar(
        select(User).where(User.id == user_id).with_for_update()
    )
    if target is None:
        return 0

    policy = None
    if target.school_id is not None:
        policy = await session.scalar(
            select(SchoolPrivacyPolicy).where(
                SchoolPrivacyPolicy.school_id == target.school_id
            )
        )
    if (
        policy is not None
        and policy.processing_mode
        != PrivacyProcessingMode.AUTOMATIC_ANONYMIZATION
    ):
        return 0

    if await active_loans(session, target.id):
        return 0

    if target.is_active:
        await anonymize_user(session, target)
        record_activity(
            session,
            target,
            operation='anonymized',
            entity_type='user',
            entity_id=target.id,
            school_id=target.school_id,
            summary=(
                'Dados do titular anonimizados após resolução de dependência'
            ),
        )

    for request in requests:
        request.status = PrivacyRequestStatus.FULFILLED
        request.resolution = (
            'Dados diretos anonimizados; históricos necessários foram '
            'preservados.'
        )
        record_activity(
            session,
            target,
            operation='processed',
            entity_type='privacy_request',
            entity_id=request.id,
            school_id=request.school_id,
            summary='Solicitação pendente processada automaticamente',
        )
    return len(requests)
