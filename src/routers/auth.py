from datetime import datetime
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jwt import DecodeError, ExpiredSignatureError, decode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.limiter import limiter
from src.models import RevokedToken, User
from src.schemas import Message, RefreshRequest, Token, TokenPair
from src.security import (
    create_access_token,
    create_token_pair,
    get_current_user,
    verify_password,
)
from src.settings import Settings
from src.utils.cpf import normalize_cpf

router = APIRouter(prefix='/auth', tags={'auth'})

Session = Annotated[AsyncSession, Depends(get_session)]
OAuthForm = Annotated[OAuth2PasswordRequestForm, Depends()]

settings = Settings()


@router.post('/token', response_model=TokenPair)
@limiter.limit('100/minute')
async def login_for_access_token(
    request: Request,
    form_data: OAuthForm,
    session: Session,
):
    sttm = select(User).where(
        (User.username == form_data.username)
        | (User.email == form_data.username)
    )
    user = await session.scalar(sttm)

    if not user:
        # students authenticate with CPF
        cpf = normalize_cpf(form_data.username)
        if cpf:
            user = await session.scalar(select(User).where(User.cpf == cpf))

    if not user:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )
    if not user.is_active:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='User is inactive',
        )
    if not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )

    access_token, refresh_token, _jti, _exp = create_token_pair(user.username)
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
    }


@router.post('/refresh', response_model=TokenPair)
async def refresh_token_pair(
    payload: RefreshRequest,
    session: Session,
):
    try:
        decoded = decode(
            payload.refresh_token,
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
    if not user or not user.is_active:
        await session.commit()
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='User not found or inactive',
        )

    access_token, new_refresh, _new_jti, _new_exp = create_token_pair(
        user.username
    )
    await session.commit()
    return {
        'access_token': access_token,
        'refresh_token': new_refresh,
        'token_type': 'Bearer',
    }


@router.post('/refresh_token', response_model=Token)
async def refresh_access_token(
    user: Annotated[User, Depends(get_current_user)],
):
    new_access_token = create_access_token(data={'sub': user.username})
    return {'access_token': new_access_token, 'token_type': 'Bearer'}


@router.post('/logout', response_model=Message)
async def logout(
    payload: RefreshRequest,
    session: Session,
    current_user: Annotated[User, Depends(get_current_user)],
):
    try:
        decoded = decode(
            payload.refresh_token,
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
        return {'message': 'Already logged out'}

    expires_at = datetime.fromtimestamp(exp_ts, tz=ZoneInfo('UTC'))
    session.add(RevokedToken(jti=jti, expires_at=expires_at))
    await session.commit()
    return {'message': 'Logged out successfully'}
