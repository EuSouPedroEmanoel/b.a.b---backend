from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import User
from scr.schemas import Token
from scr.security import (
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix='/auth', tags={'auth'})

Session = Annotated[AsyncSession, Depends(get_session)]
OAuthForm = Annotated[OAuth2PasswordRequestForm, Depends()]


@router.post('/token', response_model=Token)
async def login_for_access_token(form_data: OAuthForm, session: Session):
    sttm = select(User).where(User.username == form_data.username)
    user = await session.scalar(sttm)

    if not user:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )
    if not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Username or Password is wrong',
        )

    access_token = create_access_token(data={'sub': user.username})
    return {'access_token': access_token, 'token_type': 'Bearer'}


@router.post('/refresh_token', response_model=Token)
async def refresh_access_token(
    user: Annotated[User, Depends(get_current_user)],
):
    new_access_token = create_access_token(data={'sub': user.username})
    return {'access_token': new_access_token, 'token_type': 'Bearer'}
