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


def test_image_proxy_rejects_private_allowlisted_address(client, monkeypatch):
    monkeypatch.setattr(images.settings, 'IMAGE_PROXY_ALLOWED_HOSTS', '127.0.0.1')
    response = client.get(
        '/images/proxy', params={'url': 'https://127.0.0.1/cover.jpg'}
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


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


def test_image_proxy_rejects_credentials_and_non_https_urls(client):
    credentials = client.get(
        '/images/proxy',
        params={'url': 'https://user:pass@books.google.com/cover.jpg'},
    )
    http = client.get(
        '/images/proxy',
        params={'url': 'http://books.google.com/cover.jpg'},
    )

    assert credentials.status_code == HTTPStatus.BAD_REQUEST
    assert http.status_code == HTTPStatus.BAD_REQUEST


def test_image_proxy_handles_upstream_failures_and_size_limit(client, monkeypatch):
    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @staticmethod
        async def get(_url, headers):
            return SimpleNamespace(
                status_code=HTTPStatus.BAD_GATEWAY,
                headers={'content-type': 'image/jpeg'},
                content=b'not-used',
            )

    monkeypatch.setattr(images.httpx, 'AsyncClient', AsyncClient)
    upstream = client.get(
        '/images/proxy',
        params={'url': 'https://books.google.com/cover.jpg'},
    )
    assert upstream.status_code == HTTPStatus.BAD_GATEWAY

    class LargeAsyncClient(AsyncClient):
        @staticmethod
        async def get(_url, headers):
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                headers={'content-type': 'image/jpeg'},
                content=b'x' * (images.MAX_IMAGE_BYTES + 1),
            )

    monkeypatch.setattr(images.httpx, 'AsyncClient', LargeAsyncClient)
    large = client.get(
        '/images/proxy',
        params={'url': 'https://books.google.com/cover.jpg'},
    )
    assert large.status_code == HTTPStatus.CONTENT_TOO_LARGE

    class ErrorAsyncClient(AsyncClient):
        @staticmethod
        async def get(_url, headers):
            raise images.httpx.ConnectError('upstream down')

    monkeypatch.setattr(images.httpx, 'AsyncClient', ErrorAsyncClient)
    unavailable = client.get(
        '/images/proxy',
        params={'url': 'https://books.google.com/cover.jpg'},
    )
    assert unavailable.status_code == HTTPStatus.BAD_GATEWAY


def test_image_proxy_rejects_unsupported_media_type(client, monkeypatch):
    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @staticmethod
        async def get(_url, headers):
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                headers={'content-type': 'text/html'},
                content=b'<html />',
            )

    monkeypatch.setattr(images.httpx, 'AsyncClient', AsyncClient)
    response = client.get(
        '/images/proxy',
        params={'url': 'https://books.google.com/cover.jpg'},
    )

    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
