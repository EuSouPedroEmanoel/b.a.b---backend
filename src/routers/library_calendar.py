from datetime import date
from http import HTTPStatus
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    AdministrativeCapability,
    School,
    SchoolNonWorkingDay,
    User,
    UserRole,
)
from src.permissions import has_administrative_capability
from src.schemas import (
    LibraryCalendarPublic,
    NationalHolidayImportPublic,
    NonWorkingDayCreate,
    NonWorkingDayPublic,
    NonWorkingDayRangeCreate,
    NonWorkingMonthCreate,
)
from src.security import get_current_user

router = APIRouter(prefix='/library-calendar', tags=['library-calendar'])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
WEEKDAY_COUNT = 5
MONTH_COUNT = 12
MIN_HOLIDAY_YEAR = 1900
MAX_HOLIDAY_YEAR = 2100
BRASIL_API_HOLIDAYS = 'https://brasilapi.com.br/api/feriados/v1/{year}'


async def _school_or_404(school_id: int, session: AsyncSession) -> School:
    school = await session.scalar(select(School).where(School.id == school_id))
    if school is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, 'School not found')
    return school


def _can_view(user: User, school_id: int) -> bool:
    return user.role == UserRole.SUPER_ADMIN or (
        user.school_id == school_id
        and user.role in {UserRole.SCHOOL_ADMIN, UserRole.LIBRARIAN}
    )


def _can_manage(user: User, school_id: int) -> bool:
    return (
        user.role == UserRole.SCHOOL_ADMIN
        and user.school_id == school_id
    ) or has_administrative_capability(
        user, AdministrativeCapability.MANAGE_LIBRARY_CALENDAR, school_id
    )


def _ensure_view(user: User, school_id: int) -> None:
    if not _can_view(user, school_id):
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Not enough permissions')


def _ensure_manage(user: User, school_id: int) -> None:
    if not _can_manage(user, school_id):
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Not enough permissions')


async def _fetch_national_holidays(year: int) -> list[dict[str, date | str]]:
    if year < MIN_HOLIDAY_YEAR or year > MAX_HOLIDAY_YEAR:
        raise HTTPException(HTTPStatus.BAD_REQUEST, 'Ano inválido')
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(BRASIL_API_HOLIDAYS.format(year=year))
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY,
            'Não foi possível consultar os feriados nacionais.',
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, 'Resposta inválida de feriados'
        )
    holidays: list[dict[str, date | str]] = []
    for item in payload:
        if (
            not isinstance(item, dict)
            or item.get('type', 'national') != 'national'
        ):
            continue
        try:
            holiday_date = date.fromisoformat(str(item['date']))
            name = str(item['name'])
        except (KeyError, TypeError, ValueError):
            continue
        holidays.append({'date': holiday_date, 'name': name})
    return holidays


async def _holiday_preview(
    school_id: int, year: int, session: AsyncSession
) -> NationalHolidayImportPublic:
    holidays = await _fetch_national_holidays(year)
    dates = {item['date'] for item in holidays}
    existing = set((await session.scalars(
        select(SchoolNonWorkingDay.date).where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date.in_(dates),
        )
    )).all()) if dates else set()
    items = [
        {
            'date': item['date'],
            'name': item['name'],
            'already_added': item['date'] in existing,
        }
        for item in holidays
    ]
    return NationalHolidayImportPublic(
        year=year,
        holidays=items,
        added_count=len(items) - len(existing),
        already_added_count=len(existing),
    )


@router.get(
    '/{school_id}/national-holidays',
    response_model=NationalHolidayImportPublic,
)
async def preview_national_holidays(
    school_id: int, year: int, session: Session, current_user: CurrentUser
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    return await _holiday_preview(school_id, year, session)


@router.post(
    '/{school_id}/national-holidays/import',
    response_model=NationalHolidayImportPublic,
)
async def import_national_holidays(
    school_id: int, year: int, session: Session, current_user: CurrentUser
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    preview = await _holiday_preview(school_id, year, session)
    rows = [
        SchoolNonWorkingDay(school_id=school_id, date=item.date)
        for item in preview.holidays if not item.already_added
    ]
    if rows:
        session.add_all(rows)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return await _holiday_preview(school_id, year, session)
    return await _holiday_preview(school_id, year, session)


@router.get('/{school_id}', response_model=LibraryCalendarPublic)
async def get_calendar(
    school_id: int, year: int, session: Session, current_user: CurrentUser
):
    await _school_or_404(school_id, session)
    _ensure_view(current_user, school_id)
    first = date(year, 1, 1)
    last = date(year + 1, 1, 1)
    rows = (await session.scalars(
        select(SchoolNonWorkingDay)
        .where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date >= first,
            SchoolNonWorkingDay.date < last,
        )
        .order_by(SchoolNonWorkingDay.date)
    )).all()
    return {'year': year, 'days': rows}


@router.post(
    '/{school_id}/non-working-days',
    response_model=NonWorkingDayPublic,
    status_code=HTTPStatus.CREATED,
)
async def create_non_working_day(
    school_id: int,
    payload: NonWorkingDayCreate,
    session: Session,
    current_user: CurrentUser,
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    row = SchoolNonWorkingDay(school_id=school_id, **payload.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            HTTPStatus.CONFLICT, 'Este dia já está marcado para a escola'
        )
    await session.refresh(row)
    return row


@router.post(
    '/{school_id}/non-working-days/range',
    response_model=list[NonWorkingDayPublic],
    status_code=HTTPStatus.CREATED,
)
async def create_non_working_range(
    school_id: int,
    payload: NonWorkingDayRangeCreate,
    session: Session,
    current_user: CurrentUser,
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    existing = set((await session.scalars(
        select(SchoolNonWorkingDay.date).where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date >= payload.start_date,
            SchoolNonWorkingDay.date <= payload.end_date,
        )
    )).all())
    rows = []
    current = payload.start_date
    while current <= payload.end_date:
        if current.weekday() < WEEKDAY_COUNT and current not in existing:
            rows.append(SchoolNonWorkingDay(
                school_id=school_id,
                date=current,
            ))
        current = current.fromordinal(current.toordinal() + 1)
    session.add_all(rows)
    await session.commit()
    return rows


@router.post(
    '/{school_id}/non-working-days/month',
    response_model=list[NonWorkingDayPublic],
    status_code=HTTPStatus.CREATED,
)
async def create_non_working_month(
    school_id: int,
    payload: NonWorkingMonthCreate,
    session: Session,
    current_user: CurrentUser,
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    first = date(payload.year, payload.month, 1)
    last = date(
        payload.year + (payload.month == MONTH_COUNT),
        payload.month % MONTH_COUNT + 1,
        1,
    )
    existing = set((await session.scalars(
        select(SchoolNonWorkingDay.date).where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date >= first,
            SchoolNonWorkingDay.date < last,
        )
    )).all())
    rows = []
    current = first
    while current < last:
        if current.weekday() < WEEKDAY_COUNT and current not in existing:
            rows.append(SchoolNonWorkingDay(school_id=school_id, date=current))
        current = current.fromordinal(current.toordinal() + 1)
    if rows:
        session.add_all(rows)
        await session.commit()
    return rows


@router.delete(
    '/{school_id}/non-working-days/month/{year}/{month}',
    status_code=HTTPStatus.NO_CONTENT,
)
async def delete_non_working_month(
    school_id: int,
    year: int,
    month: int,
    session: Session,
    current_user: CurrentUser,
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    if (
        year < MIN_HOLIDAY_YEAR
        or year > MAX_HOLIDAY_YEAR
        or month not in range(1, MONTH_COUNT + 1)
    ):
        raise HTTPException(HTTPStatus.BAD_REQUEST, 'Mês inválido')
    first = date(year, month, 1)
    last = date(
        year + (month == MONTH_COUNT), month % MONTH_COUNT + 1, 1
    )
    await session.execute(delete(SchoolNonWorkingDay).where(
        SchoolNonWorkingDay.school_id == school_id,
        SchoolNonWorkingDay.date >= first,
        SchoolNonWorkingDay.date < last,
    ))
    await session.commit()


@router.delete(
    '/{school_id}/non-working-days/{day}', status_code=HTTPStatus.NO_CONTENT
)
async def delete_non_working_day(
    school_id: int,
    day: date,
    session: Session,
    current_user: CurrentUser,
):
    await _school_or_404(school_id, session)
    _ensure_manage(current_user, school_id)
    result = await session.execute(
        delete(SchoolNonWorkingDay).where(
            SchoolNonWorkingDay.school_id == school_id,
            SchoolNonWorkingDay.date == day,
        )
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(HTTPStatus.NOT_FOUND, 'Dia não encontrado')
