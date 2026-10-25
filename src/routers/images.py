import ipaddress
from http import HTTPStatus
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.settings import Settings

router = APIRouter(prefix='/images', tags={'images'})
settings = Settings()
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_MEDIA_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def _validate_image_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    host = (parsed.hostname or '').lower()
    invalid_scheme = parsed.scheme != 'https' or not host
    invalid_credentials = bool(parsed.username or parsed.password)
    invalid_port = parsed.port not in {None, 443}
    invalid_host = host not in settings.image_proxy_allowed_hosts
    if invalid_scheme or invalid_credentials or invalid_port or invalid_host:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST, 'URL de imagem não permitida'
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (
        address.is_private or address.is_loopback or address.is_link_local
    ):
        raise HTTPException(
            HTTPStatus.BAD_REQUEST, 'URL de imagem não permitida'
        )
    return parsed.geturl()


@router.get('/proxy')
async def proxy_image(
    url: Annotated[str, Query(min_length=1, max_length=2048)],
):
    target = _validate_image_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False
        ) as client:
            response = await client.get(
                target,
                headers={'Accept': 'image/avif,image/webp,image/*;q=0.8'},
            )
    except httpx.HTTPError:
        raise HTTPException(HTTPStatus.BAD_GATEWAY, 'Imagem indisponível')

    if response.status_code != HTTPStatus.OK:
        raise HTTPException(HTTPStatus.BAD_GATEWAY, 'Imagem indisponível')
    media_type = (
        response.headers.get('content-type', '').split(';', 1)[0].lower()
    )
    if media_type not in IMAGE_MEDIA_TYPES:
        raise HTTPException(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            'Tipo de imagem não permitido',
        )
    if len(response.content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            HTTPStatus.CONTENT_TOO_LARGE, 'Imagem muito grande'
        )
    return Response(
        content=response.content,
        media_type=media_type,
        headers={'Cache-Control': 'public, max-age=86400'},
    )
