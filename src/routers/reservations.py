from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_session
from src.models import (
    BookCopy,
    BooksStates,
    Reservation,
    ReservationStatus,
    User,
    UserRole,
)
from src.schemas import (
    FilterReservation,
    Message,
    PaginatedResponse,
    ReservationCreate,
    ReservationPublic,
)
from src.security import get_current_user
from src.utils.pagination import paginate
from src.utils.reservation_queue import (
    lock_book_queue,
    promote_copy_to_next_reservation,
)

router = APIRouter(prefix='/reservations', tags=['reservations'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def reservation_public(
    reservation: Reservation,
    queue_position: int | None = None,
    queue_total: int | None = None,
):
    return {
        'id': reservation.id,
        'book_id': reservation.book_id,
        'user_id': reservation.user_id,
        'school_id': reservation.school_id,
        'status': reservation.status,
        'created_at': reservation.created_at,
        'copy_id': reservation.copy_id,
        'book_title': reservation.book.title,
        'book_cover_url': reservation.book.cover_url,
        'reserver_username': reservation.reserver.username,
        'reserver_role': reservation.reserver.role,
        'reserver_is_active': reservation.reserver.is_active,
        'reserver_turma_numero': reservation.reserver.turma_numero,
        'reserver_turma_letra': reservation.reserver.turma_letra,
        'internal_code': reservation.copy.code if reservation.copy else None,
        'queue_position': queue_position,
        'queue_total': queue_total,
        'ready_at': reservation.ready_at,
        'pickup_expires_at': reservation.pickup_expires_at,
    }


async def queue_positions(session: Session, items: list[Reservation]):
    positions: dict[int, int] = {}
    totals: dict[tuple[int, int], int] = {}
    groups = {(item.book_id, item.school_id) for item in items
              if item.status in {
                  ReservationStatus.ACTIVE, ReservationStatus.READY
              }}
    for book_id, school_id in groups:
        ordered = (await session.scalars(
            select(Reservation.id).where(
                Reservation.book_id == book_id,
                Reservation.school_id == school_id,
                Reservation.status.in_([
                    ReservationStatus.ACTIVE, ReservationStatus.READY
                ]),
            ).order_by(Reservation.created_at, Reservation.id)
        )).all()
        totals[(book_id, school_id)] = len(ordered)
        positions.update({reservation_id: index for index, reservation_id in
                          enumerate(ordered, start=1)})
    return positions, totals


@router.post(
    '/', response_model=ReservationPublic, status_code=HTTPStatus.CREATED
)
async def create_reservation(
    payload: ReservationCreate,
    session: Session,
    current_user: CurrentUser,
):
    if current_user.role not in {UserRole.STUDENT, UserRole.TEACHER}:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Only STUDENT/TEACHER can create reservations',
        )
    if current_user.school_id is None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='User without school'
        )

    book = await lock_book_queue(session, payload.book_id)
    if not book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found'
        )
    if not book.is_active:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Book is inactive'
        )

    # Book row lock serializes availability and queue changes for this title.
    existing = await session.scalar(
        select(Reservation).where(
            Reservation.book_id == book.id,
            Reservation.user_id == current_user.id,
            Reservation.school_id == current_user.school_id,
            Reservation.status.in_([
                ReservationStatus.ACTIVE,
                ReservationStatus.READY,
            ]),
        )
    )
    if existing:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Active reservation already exists',
        )

    # only allow if no available copies for this book in user's school
    available = await session.scalar(
        select(BookCopy).where(
            BookCopy.book_id == book.id,
            BookCopy.school_id == current_user.school_id,
            BookCopy.state == BooksStates.AVAILABLE,
        )
    )
    if available:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='There are available copies; reservation not needed',
        )

    reservation = Reservation(
        book_id=book.id,
        user_id=current_user.id,
        school_id=current_user.school_id,
        status=ReservationStatus.ACTIVE,
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)
    await session.refresh(
        reservation, attribute_names=['book', 'reserver', 'copy']
    )
    positions, totals = await queue_positions(session, [reservation])
    key = (reservation.book_id, reservation.school_id)
    return reservation_public(reservation, positions.get(reservation.id),
                              totals.get(key))


@router.get('/', response_model=PaginatedResponse[ReservationPublic])
async def list_reservations(
    session: Session,
    current_user: CurrentUser,
    filt: Annotated[FilterReservation, Depends()],
):
    query = select(Reservation).options(
        selectinload(Reservation.book),
        selectinload(Reservation.reserver),
        selectinload(Reservation.copy),
    )

    # Students/Teachers see only own; staff see school's
    if current_user.role in {UserRole.STUDENT, UserRole.TEACHER}:
        query = query.where(Reservation.user_id == current_user.id)
    elif current_user.role == UserRole.SUPER_ADMIN:
        pass
    else:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='User without school'
            )
        query = query.where(Reservation.school_id == current_user.school_id)

    if filt.status:
        query = query.where(Reservation.status == filt.status)
    if filt.book_id:
        query = query.where(Reservation.book_id == filt.book_id)

    query = query.order_by(Reservation.created_at)
    items, total, page, size, pages = await paginate(session, query, filt)
    positions, totals = await queue_positions(session, items)
    return {
        'items': [
            reservation_public(
                item, positions.get(item.id),
                totals.get((item.book_id, item.school_id)),
            ) for item in items
        ],
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/me', response_model=PaginatedResponse[ReservationPublic])
async def list_my_reservations(
    session: Session,
    current_user: CurrentUser,
    filt: Annotated[FilterReservation, Depends()],
):
    query = select(Reservation).options(
        selectinload(Reservation.book), selectinload(Reservation.reserver),
        selectinload(Reservation.copy),
    ).where(Reservation.user_id == current_user.id)
    if filt.status:
        query = query.where(Reservation.status == filt.status)
    if filt.book_id:
        query = query.where(Reservation.book_id == filt.book_id)
    query = query.order_by(Reservation.created_at)
    items, total, page, size, pages = await paginate(session, query, filt)
    positions, totals = await queue_positions(session, items)
    return {
        'items': [
            reservation_public(
                item, positions.get(item.id),
                totals.get((item.book_id, item.school_id)),
            ) for item in items
        ],
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/{reservation_id}', response_model=ReservationPublic)
async def get_reservation(
    reservation_id: int, session: Session, current_user: CurrentUser
):
    reservation = await session.scalar(
        select(Reservation).options(
            selectinload(Reservation.book), selectinload(Reservation.reserver),
            selectinload(Reservation.copy),
        ).where(Reservation.id == reservation_id)
    )
    if not reservation:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Reservation not found'
        )
    if current_user.role != UserRole.SUPER_ADMIN and (
        reservation.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Reservation not found'
        )
    if current_user.role in {UserRole.STUDENT, UserRole.TEACHER} and (
        reservation.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )
    positions, totals = await queue_positions(session, [reservation])
    return reservation_public(
        reservation,
        positions.get(reservation.id),
        totals.get((reservation.book_id, reservation.school_id)),
    )


@router.delete('/{reservation_id}', response_model=Message)
async def cancel_reservation(
    reservation_id: int,
    session: Session,
    current_user: CurrentUser,
):
    initial = await session.scalar(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    if not initial:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Reservation not found'
        )
    await lock_book_queue(session, initial.book_id)
    reservation = await session.scalar(
        select(Reservation).options(selectinload(Reservation.copy)).where(
            Reservation.id == reservation_id
        ).with_for_update()
    )
    if not reservation:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Reservation not found'
        )

    # only owner or staff of same school or super admin
    is_owner = reservation.user_id == current_user.id
    is_staff_same_school = (
        current_user.role in {UserRole.LIBRARIAN, UserRole.SCHOOL_ADMIN}
        and reservation.school_id == current_user.school_id
    )
    is_super = current_user.role == UserRole.SUPER_ADMIN
    if not (is_owner or is_staff_same_school or is_super):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    if reservation.status not in {
        ReservationStatus.ACTIVE,
        ReservationStatus.READY,
    }:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Reservation is not active'
        )

    reserved_copy = reservation.copy
    reservation.status = ReservationStatus.CANCELLED
    session.add(reservation)
    if reserved_copy is not None:
        copy = await session.scalar(
            select(BookCopy)
            .where(BookCopy.id == reserved_copy.id)
            .with_for_update()
        )
        if copy is not None:
            await promote_copy_to_next_reservation(session, copy)
    await session.commit()
    return {'message': 'Reservation cancelled'}
