from http import HTTPStatus


def test_root_deve_retornar_ola_mundo(client):

    response = client.get('/')
    assert response.json() == {'message': 'olá mundo'}
    assert response.status_code == HTTPStatus.OK


def test_rate_limit_handler():
    import asyncio
    from unittest.mock import MagicMock

    from fastapi import Request
    from slowapi.errors import RateLimitExceeded

    from src.app import rate_limit_handler

    mock_request = MagicMock(spec=Request)
    mock_exc = MagicMock(spec=RateLimitExceeded)

    result = asyncio.run(rate_limit_handler(mock_request, mock_exc))
    assert result.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert result.body is not None


def test_paginated_response_helper():
    from src.utils.pagination import paginated_response

    r = paginated_response([], 0, 1, 10)
    assert r['pages'] == 0
    assert r['total'] == 0
    r2 = paginated_response([1, 2], 2, 1, 10)
    assert r2['pages'] == 1
    assert r2['total'] == 2
    r3 = paginated_response([1] * 25, 25, 1, 10)
    assert r3['pages'] == 3
