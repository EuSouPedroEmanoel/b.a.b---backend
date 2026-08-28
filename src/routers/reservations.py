from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    Book,
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

router = APIRouter(prefix='/reservations', tags=['reservations'])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


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

    book = await session.scalar(select(Book).where(Book.id == payload.book_id))
    if not book:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Book not found'
        )
    if not book.is_active:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Book is inactive'
        )

    # check already has active reservation for same book
    existing = await session.scalar(
        select(Reservation).where(
            Reservation.book_id == book.id,
            Reservation.user_id == current_user.id,
            Reservation.school_id == current_user.school_id,
            Reservation.status == ReservationStatus.ACTIVE,
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
    return reservation


@router.get('/', response_model=PaginatedResponse[ReservationPublic])
async def list_reservations(
    session: Session,
    current_user: CurrentUser,
    filt: Annotated[FilterReservation, Depends()],
):
    query = select(Reservation)

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
    return {
        'items': items,
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
    query = select(Reservation).where(Reservation.user_id == current_user.id)
    if filt.status:
        query = query.where(Reservation.status == filt.status)
    if filt.book_id:
        query = query.where(Reservation.book_id == filt.book_id)
    query = query.order_by(Reservation.created_at)
    items, total, page, size, pages = await paginate(session, query, filt)
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.delete('/{reservation_id}', response_model=Message)
async def cancel_reservation(
    reservation_id: int,
    session: Session,
    current_user: CurrentUser,
):
    reservation = await session.scalar(
        select(Reservation).where(Reservation.id == reservation_id)
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

    if reservation.status != ReservationStatus.ACTIVE:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='Reservation is not active'
        )

    reservation.status = ReservationStatus.CANCELLED
    session.add(reservation)
    await session.commit()
    return {'message': 'Reservation cancelled'}
