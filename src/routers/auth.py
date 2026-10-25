import secrets
from datetime import datetime
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from jwt import DecodeError, ExpiredSignatureError, decode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.limiter import limiter
from src.models import AccountStatus, RevokedToken, School, User
from src.schemas import (
    CurrentUserPublic,
    GuestAccessRequest,
    GuestSchoolPublic,
    Message,
    RefreshRequest,
    SessionPublic,
    Token,
    TokenPair,
)
from src.security import (
    create_access_token,
    create_guest_token,
    create_token_pair,
    get_current_user,
    is_guest,
    verify_password,
)
from src.settings import Settings
from src.utils.cpf import (
    cpf_collision_guard,
    cpf_lookup_digest,
    normalize_cpf,
    validate_cpf,
)

router = APIRouter(prefix='/auth', tags={'auth'})

Session = Annotated[AsyncSession, Depends(get_session)]
OAuthForm = Annotated[OAuth2PasswordRequestForm, Depends()]

settings = Settings()


@router.get('/guest/schools', response_model=list[GuestSchoolPublic])
async def list_guest_schools(session: Session):
    return (
        await session.scalars(
            select(School)
            .where(School.is_active.is_(True))
            .order_by(School.name)
        )
    ).all()


@router.post('/guest', response_model=Token)
@limiter.limit('20/minute')
async def create_guest_access_token(
    request: Request,
    payload: GuestAccessRequest,
    session: Session,
    response: Response,
):
    school = await session.scalar(
        select(School).where(
            School.code == payload.school_code.strip(),
            School.is_active.is_(True),
        )
    )
    if not school:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='School not found'
        )
    access_token = create_guest_token(school.code)
    _set_session_cookies(response, access_token)
    return {
        'access_token': access_token,
        'token_type': 'Bearer',
    }


@router.post('/token', response_model=TokenPair)
@limiter.limit('100/minute')
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: OAuthForm,
    session: Session,
    school_code: Annotated[str | None, Form()] = None,
):
    if school_code:
        sttm = (
            select(User)
            .join(School, School.id == User.school_id)
            .where(
                School.code == school_code.strip(),
                School.is_active.is_(True),
                User.school_identifier == form_data.username.strip(),
            )
        )
    else:
        sttm = select(User).where(User.username == form_data.username)
    user = await session.scalar(sttm)

    if not user and not school_code:
        # Leitores que usam CPF também podem autenticar por esse identificador.
        cpf = normalize_cpf(form_data.username)
        if cpf and validate_cpf(cpf):
            user = await session.scalar(
                select(User).where(
                    User.cpf_lookup_hash == cpf_lookup_digest(cpf),
                    User.cpf_collision_guard == cpf_collision_guard(cpf),
                )
            )

    if not user:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )
    if user.school_id is not None and not await session.scalar(
        select(School.is_active).where(School.id == user.school_id)
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='School is inactive'
        )
    if not user.is_active or user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User is inactive',
        )
    if not user.password or not verify_password(
        form_data.password, user.password
    ):
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )

    access_token, refresh_token, _jti, _exp = create_token_pair(
        user.username, user.auth_version
    )
    _set_session_cookies(response, access_token, refresh_token)
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
    }


def _set_session_cookies(
    response: Response, access_token: str, refresh_token: str | None = None
) -> None:
    common = {
        'httponly': True,
        'secure': settings.session_cookie_secure,
        'samesite': settings.SESSION_COOKIE_SAMESITE,
    }
    response.set_cookie('access_token', access_token, path='/', **common)
    if refresh_token is not None:
        response.set_cookie(
            'refresh_token', refresh_token, path='/auth', **common
        )
    response.set_cookie(
        'csrf_token',
        secrets.token_urlsafe(32),
        path='/',
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


def _require_cookie_csrf(request: Request) -> None:
    expected = request.cookies.get('csrf_token')
    provided = request.headers.get('X-CSRF-Token')
    if not expected or not provided or not secrets.compare_digest(
        expected, provided
    ):
        raise HTTPException(HTTPStatus.FORBIDDEN, 'CSRF token inválido')


@router.get('/session', response_model=SessionPublic)
async def read_session(user=Depends(get_current_user)):
    if is_guest(user):
        return {
            'user': {
                'id': 0,
                'username': 'Visitante',
                'name': 'Visitante',
                'role': 'guest',
                'school_id': user.school_id,
                'school_code': user.school_code,
                'school_name': None,
                'is_active': True,
            }
        }
    return {'user': CurrentUserPublic.model_validate(user).model_dump()}


@router.post('/refresh', response_model=TokenPair)
async def refresh_token_pair(
    request: Request,
    response: Response,
    session: Session,
    payload: RefreshRequest | None = None,
):
    refresh_token = (
        payload.refresh_token
        if payload
        else request.cookies.get('refresh_token')
    )
    if not refresh_token:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Refresh token ausente')
    if payload is None:
        _require_cookie_csrf(request)
    try:
        decoded = decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Refresh token expired'
        )
    except DecodeError:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid refresh token'
        )

    if decoded.get('type') != 'refresh':
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid token type'
        )

    jti = decoded.get('jti')
    sub = decoded.get('sub')
    if not jti or not sub:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid refresh token'
        )

    # check revoked
    revoked = await session.scalar(
        select(RevokedToken).where(RevokedToken.jti == jti)
    )
    if revoked:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Refresh token revoked'
        )

    # revoke old jti (rotation)
    exp_ts = decoded.get('exp')
    expires_at = (
        datetime.fromtimestamp(exp_ts, tz=ZoneInfo('UTC'))
        if exp_ts
        else datetime.now(tz=ZoneInfo('UTC'))
    )
    session.add(RevokedToken(jti=jti, expires_at=expires_at))

    user = await session.scalar(select(User).where(User.username == sub))
    if (
        not user
        or not user.is_active
        or user.account_status != AccountStatus.ACTIVE
        or decoded.get('auth_version', 0) != user.auth_version
    ):
        await session.commit()
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='User not found or inactive',
        )
    if user.school_id is not None and not await session.scalar(
        select(School.is_active).where(School.id == user.school_id)
    ):
        await session.commit()
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='School is inactive'
        )

    access_token, new_refresh, _new_jti, _new_exp = create_token_pair(
        user.username, user.auth_version
    )
    await session.commit()
    _set_session_cookies(response, access_token, new_refresh)
    return {
        'access_token': access_token,
        'refresh_token': new_refresh,
        'token_type': 'Bearer',
    }


@router.post('/refresh_token', response_model=Token)
async def refresh_access_token(
    user: Annotated[User, Depends(get_current_user)],
):
    new_access_token = create_access_token(
        data={'sub': user.username, 'auth_version': user.auth_version}
    )
    return {'access_token': new_access_token, 'token_type': 'Bearer'}


@router.post('/logout', response_model=Message)
async def logout(
    request: Request,
    response: Response,
    session: Session,
    current_user: Annotated[User, Depends(get_current_user)],
    payload: RefreshRequest | None = None,
):
    refresh_token = (
        payload.refresh_token
        if payload
        else request.cookies.get('refresh_token')
    )
    if not refresh_token:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Refresh token ausente')
    if payload is None:
        _require_cookie_csrf(request)
    try:
        decoded = decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except (DecodeError, ExpiredSignatureError):
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid refresh token'
        )
    if decoded.get('type') != 'refresh':
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid token type'
        )
    jti = decoded.get('jti')
    exp_ts = decoded.get('exp')
    if not jti or not exp_ts:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Invalid refresh token'
        )

    existing = await session.scalar(
        select(RevokedToken).where(RevokedToken.jti == jti)
    )
    if existing:
        response.delete_cookie('access_token', path='/')
        response.delete_cookie('refresh_token', path='/auth')
        response.delete_cookie('csrf_token', path='/')
        return {'message': 'Already logged out'}

    expires_at = datetime.fromtimestamp(exp_ts, tz=ZoneInfo('UTC'))
    session.add(RevokedToken(jti=jti, expires_at=expires_at))
    await session.commit()
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/auth')
    response.delete_cookie('csrf_token', path='/')
    return {'message': 'Logged out successfully'}
