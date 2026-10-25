from http import HTTPStatus
from types import SimpleNamespace

from src.routers import images


def test_image_proxy_rejects_untrusted_and_private_urls(client):
    external = client.get(
        '/images/proxy', params={'url': 'https://example.com/cover.jpg'}
    )
    private = client.get(
        '/images/proxy', params={'url': 'https://127.0.0.1/cover.jpg'}
    )

    assert external.status_code == HTTPStatus.BAD_REQUEST
    assert private.status_code == HTTPStatus.BAD_REQUEST


def test_image_proxy_returns_only_allowed_image_type(client, monkeypatch):
    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @staticmethod
        async def get(_url, headers):
            assert 'Referer' not in headers
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                headers={'content-type': 'image/webp'},
                content=b'fake-image',
            )

    monkeypatch.setattr(images.httpx, 'AsyncClient', AsyncClient)
    response = client.get(
        '/images/proxy',
        params={'url': 'https://books.google.com/cover.webp'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.headers['content-type'].startswith('image/webp')
    assert response.headers['cache-control'] == 'public, max-age=86400'
