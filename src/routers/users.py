from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import User, UserRole
from src.schemas import (
    FilterUser,
    Message,
    PaginatedResponse,
    StaffCreateSchema,
    StudentCreateSchema,
    UserPublic,
    UserUpdateSelf,
)
from src.security import (
    RoleChecker,
    get_current_user,
    get_password_hash,
)
from src.utils.cpf import normalize_cpf, validate_cpf
from src.utils.pagination import paginate

router = APIRouter(prefix='/users', tags={'users'})
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
StaffOnly = Annotated[
    User,
    Depends(
        RoleChecker([
            UserRole.LIBRARIAN,
            UserRole.SCHOOL_ADMIN,
            UserRole.SUPER_ADMIN,
        ])
    ),
]


@router.post('/', status_code=HTTPStatus.CREATED, response_model=UserPublic)
async def create_user(
    user: StaffCreateSchema,
    session: Session,
    current_user: StaffOnly,
):
    # SCHOOL_ADMIN/LIBRARIAN cannot choose another school; auto-assign own.
    # SUPER_ADMIN must provide school_id explicitly.
    if current_user.role == UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='school_id is required for SUPER_ADMIN',
            )
        target_school_id = user.school_id
    else:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot create users',
            )
        target_school_id = current_user.school_id

    hashed = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        cpf=user.cpf,
        password=hashed,
        role=user.role,
        school_id=target_school_id,
    )
    session.add(db_user)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists!!',
        )

    await session.refresh(db_user)
    return db_user


async def _make_unique_username(
    session: AsyncSession, name: str, cpf: str
) -> str:
    base = (
        name
        .strip()
        .lower()
        .replace(' ', '.')
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    base = base or f'student.{cpf[-4:]}'
    candidate, n = base, 1
    while (
        await session.scalar(
            select(User.username).where(User.username == candidate)
        )
        is not None
    ):
        candidate = f'{base}.{n}'
        n += 1
    return candidate


@router.post(
    '/students',
    status_code=HTTPStatus.CREATED,
    response_model=UserPublic,
)
async def create_student(
    payload: StudentCreateSchema,
    session: Session,
    current_user: StaffOnly,
):
    if current_user.role == UserRole.SUPER_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='super_admin must belong to a school or set school',
            )
        target_school_id = current_user.school_id
    else:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot create students',
            )
        target_school_id = current_user.school_id

    existing = await session.scalar(
        select(User).where(User.cpf == payload.cpf)
    )
    if existing:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
        )

    username = await _make_unique_username(session, payload.name, payload.cpf)
    hashed = get_password_hash(payload.password)
    db_user = User(
        username=username,
        email=None,
        cpf=payload.cpf,
        birthdate=payload.birthdate,
        turma_numero=payload.turma_numero,
        turma_letra=payload.turma_letra,
        password=hashed,
        role=UserRole.STUDENT,
        school_id=target_school_id,
    )
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
        )
    await session.refresh(db_user)
    return db_user


@router.get(
    '/',
    status_code=HTTPStatus.OK,
    response_model=PaginatedResponse[UserPublic],
)
async def read_users(
    current_user: CurrentUser,
    session: Session,
    filter_users: Annotated[FilterUser, Depends()],
):
    sttm = select(User).order_by(User.id)
    # Tenant isolation: SCHOOL_ADMIN / LIBRARIAN / TEACHER / STUDENT
    # only see users in same school. SUPER_ADMIN sees all.
    if current_user.role != UserRole.SUPER_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='User without school cannot list users',
            )
        sttm = sttm.where(User.school_id == current_user.school_id)
    elif filter_users.school_id is not None:
        # SUPER_ADMIN may filter users by a specific school
        sttm = sttm.where(User.school_id == filter_users.school_id)

    if filter_users.role is not None:
        sttm = sttm.where(User.role == filter_users.role)

    if filter_users.cpf is None:
        sttm = sttm.where(User.is_active.is_(True))
    else:
        sttm = sttm.where(
            User.cpf == normalize_cpf(filter_users.cpf)
        )

    items, total, page, size, pages = await paginate(
        session, sttm, filter_users
    )
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.get('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def read_user_by_id(
    user_id: int, session: Session, current_user: CurrentUser
):
    sttm = select(User).where(User.id == user_id)
    user_db = await session.scalar(sttm)

    if not user_db or not user_db.is_active:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    # Tenant isolation for non SUPER_ADMIN
    if (
        current_user.role != UserRole.SUPER_ADMIN
        and user_db.school_id != current_user.school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    return user_db


async def _apply_updates(
    session: AsyncSession,
    target: User,
    data: dict,
    is_self: bool,
    staff_can_edit: bool,
) -> None:
    if 'username' in data and is_self:
        target.username = data['username']
    if 'email' in data:
        target.email = data['email']
    if 'cpf' in data:
        cpf = normalize_cpf(data['cpf'])
        if not validate_cpf(cpf):
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail='CPF inválido',
            )
        conflict = await session.scalar(
            select(User).where(User.cpf == cpf, User.id != target.id)
        )
        if conflict:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
            )
        target.cpf = cpf
    if 'birthdate' in data:
        target.birthdate = data['birthdate']
    if 'turma_numero' in data:
        target.turma_numero = data['turma_numero']
    if 'turma_letra' in data:
        target.turma_letra = data['turma_letra']
    if 'password' in data and (is_self or staff_can_edit):
        target.password = get_password_hash(data['password'])


@router.put('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def update_user(
    user_id: int,
    user: UserUpdateSelf,
    session: Session,
    current_user: CurrentUser,
):
    target = await session.scalar(select(User).where(User.id == user_id))
    if not target:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='User Not Found...'
        )

    is_self = user_id == current_user.id
    staff_can_edit = (
        current_user.role in {UserRole.LIBRARIAN, UserRole.SCHOOL_ADMIN}
        and target.school_id == current_user.school_id
        and target.role == UserRole.STUDENT
    ) or current_user.role == UserRole.SUPER_ADMIN
    if not (is_self or staff_can_edit):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    data = user.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='No fields to update'
        )

    await _apply_updates(session, target, data, is_self, staff_can_edit)

    # role/school_id are immutable via this endpoint
    session.add(target)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists!!',
        )

    await session.refresh(target)
    return target


@router.delete('/{user_id}', status_code=HTTPStatus.OK, response_model=Message)
async def delete_user(
    user_id: int,
    session: Session,
    current_user: CurrentUser,
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Not enough permissions'
        )

    # soft delete
    current_user.is_active = False
    session.add(current_user)
    await session.commit()

    return {'message': 'User deactivated'}
