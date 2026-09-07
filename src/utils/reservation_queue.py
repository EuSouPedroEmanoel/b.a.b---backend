from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Book,
    BookCopy,
    BooksStates,
    Reservation,
    ReservationStatus,
    User,
)
from src.permissions import has_personal_reader_capability


async def lock_book_queue(session: AsyncSession, book_id: int) -> Book | None:
    """Serialize queue-changing operations for one title."""
    return await session.scalar(
        select(Book).where(Book.id == book_id).with_for_update()
    )


async def promote_copy_to_next_reservation(
    session: AsyncSession, copy: BookCopy
) -> Reservation | None:
    """Assign a returned/released copy to the oldest eligible waiting reader.

    The caller must hold the corresponding book queue lock and the copy lock.
    """
    while True:
        reservation = await session.scalar(
            select(Reservation)
            .options(selectinload(Reservation.reserver))
            .where(
                Reservation.book_id == copy.book_id,
                Reservation.school_id == copy.school_id,
                Reservation.status == ReservationStatus.ACTIVE,
            )
            .order_by(Reservation.created_at, Reservation.id)
            .with_for_update()
        )
        if reservation is None:
            copy.state = BooksStates.AVAILABLE
            return None

        reader: User = reservation.reserver
        if (
            not reader.is_active
            or reader.school_id != copy.school_id
            or not has_personal_reader_capability(reader.role)
        ):
            reservation.status = ReservationStatus.EXPIRED
            session.add(reservation)
            continue

        reservation.status = ReservationStatus.READY
        reservation.copy_id = copy.id
        reservation.ready_at = datetime.now(tz=ZoneInfo('UTC'))
        # A pickup duration is intentionally not selected until business policy
        # defines one. The nullable field preserves the future transition.
        reservation.pickup_expires_at = None
        copy.state = BooksStates.RESERVED
        session.add_all([reservation, copy])
        return reservation
