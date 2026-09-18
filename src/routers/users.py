from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    AccountActivationAudit,
    AccountStatus,
    AdministrativeCapability,
    User,
    UserAdministrativeCapability,
    UserRole,
)
from src.routers.account_activation import invitation_print_document
from src.schemas import (
    ActivationCredentials,
    ActivationInvitationPublic,
    ActivationStatePublic,
    AdministrativeCapabilitiesPublic,
    AdministrativeCapabilitiesUpdate,
    CurrentUserPublic,
    FilterUser,
    Message,
    PaginatedResponse,
    StaffCreateSchema,
    StudentCreateSchema,
    UserCreationPublic,
    UserPublic,
    UserUpdateSelf,
)
from src.security import (
    RoleChecker,
    get_current_user,
    get_password_hash,
)
from src.services.account_activation import (
    active_invitation,
    first_access_url,
    generate_invitation,
    verify_activation_hash,
)
from src.settings import Settings
from src.utils.cpf import (
    classify_cpf_candidates,
    cpf_collision_guard,
    cpf_lookup_digest,
    cpf_storage_values,
    log_cpf_lookup_collision,
    normalize_cpf,
    validate_cpf,
)
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
UserReaders = StaffOnly
settings = Settings()


def _invitation_payload(
    user_id: int,
    username: str,
    code: str,
    expires_at,
) -> ActivationInvitationPublic:
    return ActivationInvitationPublic(
        code=code,
        expires_at=expires_at,
        first_access_url=first_access_url(username, code),
        print_url=f'/users/{user_id}/activation/print',
    )


def _can_manage_target(current_user: User, target: User) -> bool:
    return current_user.role == UserRole.SUPER_ADMIN or (
        current_user.role in {UserRole.SCHOOL_ADMIN, UserRole.LIBRARIAN}
        and current_user.school_id == target.school_id
    )


async def _cpf_conflicts(
    session: AsyncSession,
    lookup_hash: bytes,
    collision_guard: bytes,
    school_id: int | None,
    exclude_user_id: int | None = None,
) -> bool:
    query = select(User.id, User.cpf_collision_guard).where(
        User.cpf_lookup_hash == lookup_hash
    )
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    candidates = list((await session.execute(query)).all())
    duplicate, collision_ids = classify_cpf_candidates(
        candidates, collision_guard
    )
    if collision_ids:
        log_cpf_lookup_collision(
            school_id=school_id, existing_user_ids=collision_ids
        )
    return duplicate


@router.put(
    '/{user_id}/administrative-capabilities',
    response_model=AdministrativeCapabilitiesPublic,
)
async def update_administrative_capabilities(
    user_id: int,
    payload: AdministrativeCapabilitiesUpdate,
    session: Session,
    current_user: CurrentUser,
):
    target = await session.scalar(select(User).where(User.id == user_id))
    if target is None or not target.is_active:
        raise HTTPException(HTTPStatus.NOT_FOUND, 'User Not Found...')
    if target.role != UserRole.LIBRARIAN:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            'Capacidades administrativas só podem ser atribuídas a '
            'bibliotecários',
        )
    allowed = current_user.role == UserRole.SUPER_ADMIN or (
        current_user.role == UserRole.SCHOOL_ADMIN
        and current_user.school_id == target.school_id
    )
    if not allowed:
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Not enough permissions')

    current = (await session.scalars(
        select(UserAdministrativeCapability).where(
            UserAdministrativeCapability.user_id == target.id
        )
    )).all()
    for assignment in current:
        await session.delete(assignment)
    for capability, enabled in {
        AdministrativeCapability.MANAGE_LIBRARY_CALENDAR:
        payload.manage_library_calendar,
        AdministrativeCapability.MANAGE_CIRCULATION_RULES:
        payload.manage_circulation_rules,
    }.items():
        if enabled:
            session.add(UserAdministrativeCapability(
                user_id=target.id, capability=capability.value
            ))
    await session.commit()
    return {
        'user_id': target.id,
        'capabilities': [
            capability for capability, enabled in {
                AdministrativeCapability.MANAGE_LIBRARY_CALENDAR:
                payload.manage_library_calendar,
                AdministrativeCapability.MANAGE_CIRCULATION_RULES:
                payload.manage_circulation_rules,
            }.items() if enabled
        ],
    }


@router.post(
    '/', status_code=HTTPStatus.CREATED, response_model=UserCreationPublic
)
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

    lookup_hash, collision_guard, last2 = cpf_storage_values(user.cpf)
    if await _cpf_conflicts(
        session, lookup_hash, collision_guard, target_school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists!!',
        )
    db_user = User(
        username=user.username,
        name=user.name or user.username,
        email=user.email,
        cpf_lookup_hash=lookup_hash,
        cpf_collision_guard=collision_guard,
        cpf_last2=last2,
        password=None,
        role=user.role,
        school_id=target_school_id,
        account_status=AccountStatus.PENDING_ACTIVATION,
    )
    session.add(db_user)

    try:
        await session.flush()
        invitation, code = await generate_invitation(
            session, db_user, current_user.id
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Username, Email or CPF already exists!!',
        )

    await session.refresh(db_user)
    return {
        **UserPublic.model_validate(db_user).model_dump(),
        'activation_invitation': _invitation_payload(
            db_user.id, db_user.username, code, invitation.expires_at
        ),
    }


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
    response_model=UserCreationPublic,
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

    lookup_hash, collision_guard, last2 = cpf_storage_values(payload.cpf)
    if await _cpf_conflicts(
        session, lookup_hash, collision_guard, target_school_id
    ):
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
        )

    username = await _make_unique_username(session, payload.name, payload.cpf)
    db_user = User(
        username=username,
        name=payload.name,
        email=None,
        cpf_lookup_hash=lookup_hash,
        cpf_collision_guard=collision_guard,
        cpf_last2=last2,
        birthdate=payload.birthdate,
        turma_numero=payload.turma_numero,
        turma_letra=payload.turma_letra,
        password=None,
        role=UserRole.STUDENT,
        school_id=target_school_id,
        account_status=AccountStatus.PENDING_ACTIVATION,
    )
    session.add(db_user)
    try:
        await session.flush()
        invitation, code = await generate_invitation(
            session, db_user, current_user.id
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
        )
    await session.refresh(db_user)
    return {
        **UserPublic.model_validate(db_user).model_dump(),
        'activation_invitation': _invitation_payload(
            db_user.id, db_user.username, code, invitation.expires_at
        ),
    }


@router.get(
    '/',
    status_code=HTTPStatus.OK,
    response_model=PaginatedResponse[UserPublic],
)
async def read_users(
    current_user: UserReaders,
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
            User.cpf_lookup_hash == cpf_lookup_digest(filter_users.cpf),
            User.cpf_collision_guard == cpf_collision_guard(filter_users.cpf),
            User.is_active.is_(True),
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


@router.get('/me', status_code=HTTPStatus.OK, response_model=CurrentUserPublic)
async def read_current_user(current_user: CurrentUser):
    return current_user


async def _activation_target(
    session: AsyncSession, user_id: int, current_user: User
) -> User:
    target = await session.scalar(select(User).where(User.id == user_id))
    if target is None or not _can_manage_target(current_user, target):
        raise HTTPException(HTTPStatus.NOT_FOUND, 'User Not Found...')
    return target


@router.get(
    '/{user_id}/activation', response_model=ActivationStatePublic
)
async def read_activation_state(
    user_id: int, session: Session, current_user: StaffOnly
):
    target = await _activation_target(session, user_id, current_user)
    invitation = await active_invitation(session, target.id)
    return {
        'account_status': target.account_status,
        'has_active_invitation': invitation is not None,
        'expires_at': invitation.expires_at if invitation else None,
    }


@router.post(
    '/{user_id}/activation/regenerate',
    response_model=ActivationInvitationPublic,
)
async def regenerate_activation(
    user_id: int, session: Session, current_user: StaffOnly
):
    target = await _activation_target(session, user_id, current_user)
    if target.account_status != AccountStatus.PENDING_ACTIVATION:
        raise HTTPException(
            HTTPStatus.CONFLICT,
            'Somente contas pendentes podem receber um novo convite.',
        )
    invitation, code = await generate_invitation(
        session, target, current_user.id, event='reissued'
    )
    await session.commit()
    return _invitation_payload(
        target.id, target.username, code, invitation.expires_at
    )


@router.post(
    '/{user_id}/activation/revoke', response_model=Message
)
async def revoke_activation(
    user_id: int, session: Session, current_user: StaffOnly
):
    target = await _activation_target(session, user_id, current_user)
    invitation = await active_invitation(session, target.id, for_update=True)
    if invitation:
        invitation.revoked_at = datetime.utcnow()
        session.add(
            AccountActivationAudit(
                user_id=target.id,
                actor_id=current_user.id,
                event='revoked',
            )
        )
        await session.commit()
    return {'message': 'Convite revogado.'}


@router.post(
    '/{user_id}/activation/print', response_class=HTMLResponse
)
async def print_activation_invitation(
    user_id: int,
    payload: ActivationCredentials,
    session: Session,
    current_user: StaffOnly,
):
    target = await _activation_target(session, user_id, current_user)
    invitation = await active_invitation(session, target.id)
    if (
        invitation is None
        or payload.username != target.username
        or not verify_activation_hash(payload.code, invitation.code_hash)
    ):
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            'Não foi possível gerar o documento do convite.',
        )
    return invitation_print_document(
        name=target.name,
        username=target.username,
        code=payload.code,
        expires_at=invitation.expires_at,
    )


@router.get('/{user_id}', status_code=HTTPStatus.OK, response_model=UserPublic)
async def read_user_by_id(
    user_id: int, session: Session, current_user: UserReaders
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
    if 'name' in data and data['name'] is not None:
        target.name = data['name']
    if 'email' in data:
        target.email = data['email']
    if 'cpf' in data:
        cpf = normalize_cpf(data['cpf'])
        if not validate_cpf(cpf):
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail='CPF inválido',
            )
        lookup_hash, collision_guard, last2 = cpf_storage_values(cpf)
        conflict = await _cpf_conflicts(
            session,
            lookup_hash,
            collision_guard,
            target.school_id,
            exclude_user_id=target.id,
        )
        if conflict:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT, detail='CPF already exists'
            )
        target.cpf_lookup_hash = lookup_hash
        target.cpf_collision_guard = collision_guard
        target.cpf_last2 = last2
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
    ) or (
        current_user.role == UserRole.SUPER_ADMIN
        and target.role == UserRole.SCHOOL_ADMIN
    )
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
    current_user.account_status = AccountStatus.DISABLED
    current_user.auth_version += 1
    session.add(current_user)
    await session.commit()

    return {'message': 'User deactivated'}
    ActivationCredentials,
    ActivationInvitationPublic,
    ActivationStatePublic,
