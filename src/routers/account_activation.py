from datetime import datetime
from html import escape
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from qrcode import QRCode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.svg import SvgPathImage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import (
    AccountActivationAudit,
    AccountActivationToken,
    AccountStatus,
)
from src.schemas import (
    ActivationComplete,
    ActivationCredentials,
    ActivationValidatePublic,
    Message,
)
from src.security import get_password_hash
from src.services.account_activation import (
    ActivationError,
    first_access_url,
    validate_activation_password,
    verify_invitation,
)
from src.settings import Settings

router = APIRouter(prefix='/account-activation', tags={'account activation'})
Session = Annotated[AsyncSession, Depends(get_session)]
settings = Settings()


def _qr_code_svg(value: str) -> str:
    qr = QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(value)
    qr.make(fit=True)
    return qr.make_image(image_factory=SvgPathImage).to_string().decode()


def _origin(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',', maxsplit=1)[0].strip()
    return request.client.host if request.client else 'unknown'


@router.post('/validate', response_model=ActivationValidatePublic)
async def validate_account_activation(
    payload: ActivationCredentials,
    request: Request,
    session: Session,
):
    try:
        await verify_invitation(
            session,
            payload.username,
            payload.code,
            _origin(request),
            event='validate',
        )
        await session.commit()
    except ActivationError as exc:
        await session.commit()
        raise HTTPException(HTTPStatus.BAD_REQUEST, str(exc))
    return {'valid': True}


@router.post('/complete', response_model=Message)
async def complete_account_activation(
    payload: ActivationComplete,
    request: Request,
    session: Session,
):
    try:
        await _complete_activation(payload, request, session)
    except ActivationError as exc:
        await session.commit()
        raise HTTPException(HTTPStatus.BAD_REQUEST, str(exc))
    return {'message': 'Conta ativada com sucesso. Entre com sua nova senha.'}


async def _complete_activation(
    payload: ActivationComplete,
    request: Request,
    session: AsyncSession,
) -> None:
    validate_activation_password(payload.password)
    user, invitation = await verify_invitation(
        session,
        payload.username,
        payload.code,
        _origin(request),
        event='complete',
        for_update=True,
    )
    now = datetime.utcnow()
    user.password = get_password_hash(payload.password)
    user.account_status = AccountStatus.ACTIVE
    user.activated_at = now
    user.auth_version += 1
    invitation.used_at = now
    await session.execute(
        update(AccountActivationToken)
        .where(
            AccountActivationToken.user_id == user.id,
            AccountActivationToken.id != invitation.id,
            AccountActivationToken.used_at.is_(None),
            AccountActivationToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    session.add(
        AccountActivationAudit(
            user_id=user.id,
            event='activated',
            origin_hash=None,
        )
    )
    await session.commit()


def invitation_print_document(
    *, name: str, username: str, code: str, expires_at: datetime
) -> HTMLResponse:
    access_url = first_access_url(username, code)
    formatted_expiry = expires_at.strftime('%d/%m/%Y às %H:%M')
    html = f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Convite de primeiro acesso</title>
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: system-ui, sans-serif; color: #111; margin: 0; }}
main {{ max-width: 44rem; border: 2px solid #111; padding: 1.5rem; }}
h1 {{ font-size: 1.5rem; margin: 0 0 1.5rem; }}
p {{ line-height: 1.5; margin: .5rem 0; overflow-wrap: anywhere; }}
.code {{ font-size: 1.75rem; font-weight: 700; letter-spacing: .12em;
margin: 1.5rem 0; }}
.notice {{ border-top: 1px solid #111; margin-top: 1.5rem;
padding-top: 1rem; }}
.qr-wrap {{ margin: 1.5rem 0; text-align: center; }}
.qr-wrap svg {{ display: block; width: 8rem; height: 8rem;
margin: .75rem auto 0; }}
@media print {{ button {{ display: none; }} main {{ break-inside: avoid; }} }}
</style></head><body><main>
<h1>Primeiro acesso à Biblioteca</h1>
<p><strong>Aluno:</strong> {escape(name)}</p>
<p><strong>Usuário:</strong> {escape(username)}</p>
<p class="code"><strong>Código de ativação:</strong> {escape(code)}</p>
<p><strong>Acesse:</strong><br>{escape(access_url)}</p>
<div class="qr-wrap"><p><strong>Aponte a câmera do celular:</strong></p>
{_qr_code_svg(access_url)}</div>
<p class="notice">Este código é pessoal, de uso único e válido até
{escape(formatted_expiry)}.<br>
Caso expire ou seja perdido, procure a biblioteca.</p>
<button type="button" onclick="window.print()">Imprimir</button>
</main></body></html>'''
    return HTMLResponse(
        html,
        headers={'Cache-Control': 'no-store, private', 'Pragma': 'no-cache'},
    )
