from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import DecodeError, ExpiredSignatureError, decode, encode
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scr.database import get_session
from scr.models import User
from scr.settings import Settings

pwd_context = PasswordHash.recommended()
settings = Settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='auth/token')


def get_password_hash(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    to_encode = data.copy()

    expire = datetime.now(tz=ZoneInfo('UTC')) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update({'exp': expire})

    encoded_jwt = encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

    return encoded_jwt


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str = Depends(oauth2_scheme),
):
    credential_exception = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )

    try:
        payload = decode(token, settings.SECRET_KEY, settings.ALGORITHM)
        subject_username = payload.get('sub')
        if not subject_username:
            raise credential_exception
    except DecodeError:
        raise credential_exception

    except ExpiredSignatureError:
        raise credential_exception

    sttm = select(User).where(User.username == subject_username)
    user = await session.scalar(sttm)

    if not user:
        raise credential_exception

    return user
