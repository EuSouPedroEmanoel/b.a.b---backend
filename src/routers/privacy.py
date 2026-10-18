from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_session
from src.models import (
    AccountStatus,
    Loan,
    LoanStatus,
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
    UserRole,
)
from src.schemas import (
    FilterPage,
    PaginatedResponse,
    PrivacyExportRequest,
    PrivacyPolicyPublic,
    PrivacyPolicyUpdate,
    PrivacyProfilePublic,
    PrivacyRequestCreate,
    PrivacyRequestDecision,
    PrivacyRequestPublic,
)
from src.security import get_current_user, is_guest, verify_password
from src.services.administrative_activity import record_activity
from src.utils.pagination import paginate

router = APIRouter(prefix='/privacy', tags=['privacy'])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]

SHARING = [
    'A escola responsável pela sua conta utiliza os dados para operar '
    'a biblioteca.',
    'Dados técnicos podem ser processados pelos serviços necessários ao '
    'funcionamento do produto.',
    'Não há consentimentos opcionais registrados para revogação nesta versão.',
]
PRESERVATION = [
    'Empréstimos ativos precisam permanecer associados à conta até a '
    'devolução.',
    'Históricos necessários à integridade operacional, segurança ou '
    'auditoria podem ser preservados.',
    'Pedidos de eliminação podem ser atendidos parcialmente quando houver '
    'preservação necessária.',
]


def _require_account(user: User) -> User:
    if is_guest(user):
        raise HTTPException(
            HTTPStatus.FORBIDDEN, 'Entre com sua conta para continuar.'
        )
    return user


def _require_privacy_operator(user: User) -> User:
    _require_account(user)
    if user.role not in {
        UserRole.LIBRARIAN,
        UserRole.SCHOOL_ADMIN,
        UserRole.SUPER_ADMIN,
    }:
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Not enough permissions')
    return user


async def _verify_sensitive_password(user: User, password: str | None) -> None:
    if (
        not password
        or not user.password
        or not verify_password(password, user.password)
    ):
        raise HTTPException(
            HTTPStatus.UNAUTHORIZED, 'Confirmação de senha inválida'
        )


async def _active_loans(session: AsyncSession, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(Loan.id)).where(
                Loan.user_id == user_id, Loan.status == LoanStatus.ACTIVE
            )
        )
        or 0
    )


async def _anonymize_user(session: AsyncSession, target: User) -> None:
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


@router.get('/me', response_model=PrivacyProfilePublic)
async def read_privacy_profile(session: Session, user: CurrentUser):
    user = _require_account(user)
    loans = list(
        (
            await session.scalars(
                select(Loan)
                .options(selectinload(Loan.copy))
                .where(Loan.user_id == user.id)
            )
        ).all()
    )
    reservations = list(
        (
            await session.scalars(
                select(Reservation).where(Reservation.user_id == user.id)
            )
        ).all()
    )
    favorites = int(
        await session.scalar(
            select(func.count(UserBookFavorite.id)).where(
                UserBookFavorite.user_id == user.id
            )
        )
        or 0
    )
    reading_statuses = int(
        await session.scalar(
            select(func.count(UserReadingStatus.id)).where(
                UserReadingStatus.user_id == user.id
            )
        )
        or 0
    )
    return {
        'account': {
            'name': user.name,
            'username': user.username,
            'cpf_masked': user.cpf_masked,
            'birthdate': user.birthdate,
            'class': f'{user.turma_numero}º {user.turma_letra}'
            if user.turma_numero and user.turma_letra
            else None,
            'school': user.school_name,
            'role': user.role.value,
            'status': user.account_status.value,
        },
        'library': {
            'loans_total': len(loans),
            'active_loans': sum(
                loan.status == LoanStatus.ACTIVE for loan in loans
            ),
            'reservations_total': len(reservations),
            'active_reservations': sum(
                item.status
                in {ReservationStatus.ACTIVE, ReservationStatus.READY}
                for item in reservations
            ),
        },
        'preferences': {
            'favorites': favorites,
            'reading_statuses': reading_statuses,
        },
        'security': {'password': 'Não exibida', 'tokens': 'Não exibidos'},
        'sharing': SHARING,
        'correction_guidance': [
            'Nome, data de nascimento e turma podem ser corrigidos pelo '
            'perfil quando o formulário permitir.',
            'Dados administrativos ou de segurança devem ser solicitados à '
            'escola responsável.',
        ],
        'preservation': PRESERVATION,
    }


@router.post('/me/export')
async def export_privacy_data(
    payload: PrivacyExportRequest, session: Session, user: CurrentUser
):
    user = _require_account(user)
    await _verify_sensitive_password(user, payload.password)
    loans = list(
        (
            await session.scalars(select(Loan).where(Loan.user_id == user.id))
        ).all()
    )
    reservations = list(
        (
            await session.scalars(
                select(Reservation).where(Reservation.user_id == user.id)
            )
        ).all()
    )
    favorites = list(
        (
            await session.scalars(
                select(UserBookFavorite).where(
                    UserBookFavorite.user_id == user.id
                )
            )
        ).all()
    )
    reading = list(
        (
            await session.scalars(
                select(UserReadingStatus).where(
                    UserReadingStatus.user_id == user.id
                )
            )
        ).all()
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    record_activity(
        session,
        user,
        operation='exported',
        entity_type='privacy',
        entity_id=user.id,
        school_id=user.school_id,
        summary='Exportação de dados do titular',
        changed_fields={
            'version': '1.0',
            'categories': [
                'account',
                'loans',
                'reservations',
                'favorites',
                'reading_statuses',
            ],
        },
    )
    await session.commit()
    return JSONResponse(jsonable_encoder({
        'export_version': '1.0',
        'generated_at': generated_at,
        'categories': [
            'account',
            'loans',
            'reservations',
            'favorites',
            'reading_statuses',
        ],
        'data': {
            'account': {
                'name': user.name,
                'username': user.username,
                'cpf_masked': user.cpf_masked,
                'birthdate': user.birthdate,
                'school': user.school_name,
                'role': user.role.value,
                'account_status': user.account_status.value,
            },
            'loans': [
                {
                    'id': item.id,
                    'copy_id': item.copy_id,
                    'school_id': item.school_id,
                    'borrowed_at': item.borrowed_at,
                    'due_date': item.due_date,
                    'returned_at': item.returned_at,
                    'status': item.status.value,
                }
                for item in loans
            ],
            'reservations': [
                {
                    'id': item.id,
                    'book_id': item.book_id,
                    'school_id': item.school_id,
                    'status': item.status.value,
                    'created_at': item.created_at,
                }
                for item in reservations
            ],
            'favorites': [
                {'book_id': item.book_id, 'created_at': item.created_at}
                for item in favorites
            ],
            'reading_statuses': [
                {
                    'book_id': item.book_id,
                    'status': item.status.value,
                    'created_at': item.created_at,
                    'updated_at': item.updated_at,
                }
                for item in reading
            ],
        },
    }))


@router.post(
    '/me/requests',
    response_model=PrivacyRequestPublic,
    status_code=HTTPStatus.CREATED,
)
async def create_privacy_request(
    payload: PrivacyRequestCreate, session: Session, user: CurrentUser
):
    user = _require_account(user)
    sensitive = {
        PrivacyRequestType.ANONYMIZATION,
        PrivacyRequestType.ERASURE,
        PrivacyRequestType.BLOCKING,
    }
    if payload.request_type in sensitive:
        await _verify_sensitive_password(user, payload.password)
    request = PrivacyRequest(
        user_id=user.id,
        school_id=user.school_id,
        request_type=payload.request_type,
        description=payload.description,
    )
    session.add(request)
    await session.flush()
    if payload.request_type in sensitive:
        policy = None
        if user.school_id is not None:
            policy = await session.scalar(
                select(SchoolPrivacyPolicy).where(
                    SchoolPrivacyPolicy.school_id == user.school_id
                )
            )
        automatic = (
            policy is None
            or policy.processing_mode
            == PrivacyProcessingMode.AUTOMATIC_ANONYMIZATION
        )
        if automatic:
            active_loans = await _active_loans(session, user.id)
            if active_loans:
                request.status = PrivacyRequestStatus.PARTIALLY_FULFILLED
                request.resolution = (
                    'A anonimização aguarda a devolução dos empréstimos '
                    'ativos.'
                )
            else:
                await _anonymize_user(session, user)
                request.status = PrivacyRequestStatus.FULFILLED
                request.resolution = (
                    'Dados diretos anonimizados; históricos necessários '
                    'foram preservados.'
                )
                record_activity(
                    session,
                    user,
                    operation='anonymized',
                    entity_type='user',
                    entity_id=user.id,
                    school_id=user.school_id,
                    summary='Dados do titular anonimizados',
                )
    record_activity(
        session,
        user,
        operation='created',
        entity_type='privacy_request',
        summary=f'Solicitação de {payload.request_type.value} criada',
        school_id=user.school_id,
    )
    await session.commit()
    await session.refresh(request)
    return request


@router.get(
    '/me/requests', response_model=PaginatedResponse[PrivacyRequestPublic]
)
async def list_my_privacy_requests(
    session: Session, user: CurrentUser, page: int = 1, size: int = 20
):
    user = _require_account(user)
    rows, total, page, size, pages = await paginate(
        session,
        select(PrivacyRequest)
        .where(PrivacyRequest.user_id == user.id)
        .order_by(PrivacyRequest.created_at.desc()),
        FilterPage(page=page, size=min(size, 100)),
    )
    return {
        'items': rows,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.post(
    '/me/requests/{request_id}/cancel', response_model=PrivacyRequestPublic
)
async def cancel_privacy_request(
    request_id: int, session: Session, user: CurrentUser
):
    user = _require_account(user)
    request = await session.scalar(
        select(PrivacyRequest).where(
            PrivacyRequest.id == request_id, PrivacyRequest.user_id == user.id
        )
    )
    if not request:
        raise HTTPException(HTTPStatus.NOT_FOUND, 'Solicitação não encontrada')
    if request.status not in {
        PrivacyRequestStatus.PENDING,
        PrivacyRequestStatus.IN_REVIEW,
    }:
        raise HTTPException(
            HTTPStatus.CONFLICT, 'Solicitação não pode mais ser cancelada'
        )
    request.status = PrivacyRequestStatus.CANCELLED
    await session.commit()
    await session.refresh(request)
    return request


@router.get('/schools/{school_id}/policy', response_model=PrivacyPolicyPublic)
async def read_privacy_policy(
    school_id: int, session: Session, user: CurrentUser
):
    user = _require_privacy_operator(user)
    if user.role != UserRole.SUPER_ADMIN and user.school_id != school_id:
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Fora do escopo da escola')
    policy = await session.scalar(
        select(SchoolPrivacyPolicy).where(
            SchoolPrivacyPolicy.school_id == school_id
        )
    )
    if policy is None:
        policy = SchoolPrivacyPolicy(school_id=school_id)
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
    return policy


@router.put('/schools/{school_id}/policy', response_model=PrivacyPolicyPublic)
async def update_privacy_policy(
    school_id: int,
    payload: PrivacyPolicyUpdate,
    session: Session,
    user: CurrentUser,
):
    user = _require_privacy_operator(user)
    if user.role not in {UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN} or (
        user.role != UserRole.SUPER_ADMIN and user.school_id != school_id
    ):
        raise HTTPException(
            HTTPStatus.FORBIDDEN,
            'Apenas administradores podem alterar a política',
        )
    policy = await session.scalar(
        select(SchoolPrivacyPolicy).where(
            SchoolPrivacyPolicy.school_id == school_id
        )
    )
    old = (
        policy.processing_mode.value
        if policy
        else PrivacyProcessingMode.AUTOMATIC_ANONYMIZATION.value
    )
    if policy is None:
        policy = SchoolPrivacyPolicy(school_id=school_id)
        session.add(policy)
    policy.processing_mode = payload.processing_mode
    record_activity(
        session,
        user,
        operation='updated',
        entity_type='privacy_policy',
        entity_id=school_id,
        school_id=school_id,
        changed_fields={
            'processing_mode': {
                'from': old,
                'to': payload.processing_mode.value,
            }
        },
        summary='Política de privacidade da escola alterada',
    )
    await session.commit()
    await session.refresh(policy)
    return policy


@router.get(
    '/requests', response_model=PaginatedResponse[PrivacyRequestPublic]
)
async def list_privacy_requests(
    session: Session, user: CurrentUser, page: int = 1, size: int = 20
):
    user = _require_privacy_operator(user)
    query = select(PrivacyRequest).order_by(PrivacyRequest.created_at.desc())
    if user.role != UserRole.SUPER_ADMIN:
        if user.school_id is None:
            raise HTTPException(HTTPStatus.FORBIDDEN, 'Usuário sem escola')
        query = query.where(PrivacyRequest.school_id == user.school_id)
    rows, total, page, size, pages = await paginate(
        session, query, FilterPage(page=page, size=min(size, 100))
    )
    return {
        'items': rows,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }


@router.post(
    '/requests/{request_id}/decision', response_model=PrivacyRequestPublic
)
async def decide_privacy_request(
    request_id: int,
    payload: PrivacyRequestDecision,
    session: Session,
    user: CurrentUser,
):
    user = _require_privacy_operator(user)
    request = await session.scalar(
        select(PrivacyRequest).where(PrivacyRequest.id == request_id)
    )
    if not request or (
        user.role != UserRole.SUPER_ADMIN
        and request.school_id != user.school_id
    ):
        raise HTTPException(HTTPStatus.NOT_FOUND, 'Solicitação não encontrada')
    if payload.status not in {
        PrivacyRequestStatus.IN_REVIEW,
        PrivacyRequestStatus.FULFILLED,
        PrivacyRequestStatus.PARTIALLY_FULFILLED,
        PrivacyRequestStatus.DENIED,
    }:
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY, 'Estado de decisão inválido'
        )
    if (
        payload.status
        in {
            PrivacyRequestStatus.DENIED,
            PrivacyRequestStatus.PARTIALLY_FULFILLED,
        }
        and not payload.resolution
    ):
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY, 'Informe a justificativa'
        )
    request.status = payload.status
    request.resolution = payload.resolution
    request.decided_by = user.id
    if (
        payload.status == PrivacyRequestStatus.FULFILLED
        and request.request_type
        in {PrivacyRequestType.ANONYMIZATION, PrivacyRequestType.ERASURE}
    ):
        active_loans = await _active_loans(session, request.user_id)
        if active_loans:
            request.status = PrivacyRequestStatus.PARTIALLY_FULFILLED
            request.resolution = (
                'A anonimização aguarda a devolução dos empréstimos ativos.'
            )
        else:
            target = await session.scalar(
                select(User).where(User.id == request.user_id)
            )
            if target:
                await _anonymize_user(session, target)
                record_activity(
                    session,
                    user,
                    operation='anonymized',
                    entity_type='user',
                    entity_id=target.id,
                    school_id=request.school_id,
                    summary='Dados do titular anonimizados',
                )
    record_activity(
        session,
        user,
        operation='processed',
        entity_type='privacy_request',
        entity_id=request.id,
        school_id=request.school_id,
        summary='Solicitação de privacidade processada',
        justification=request.resolution,
    )
    await session.commit()
    await session.refresh(request)
    return request
