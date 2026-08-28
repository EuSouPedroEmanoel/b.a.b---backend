from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils import apis


@pytest.mark.asyncio
async def test_fetch_json_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'ok': True}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch('src.utils.apis.httpx.AsyncClient', return_value=mock_client):
        data = await apis._fetch_json('http://example.com')  # noqa: SLF001
        assert data == {'ok': True}


@pytest.mark.asyncio
async def test_fetch_json_non_ok():
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch('src.utils.apis.httpx.AsyncClient', return_value=mock_client):
        data = await apis._fetch_json('http://example.com')  # noqa: SLF001
        assert data is None


@pytest.mark.asyncio
async def test_fetch_json_exception():
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception('fail')
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch('src.utils.apis.httpx.AsyncClient', return_value=mock_client):
        data = await apis._fetch_json('http://example.com')  # noqa: SLF001
        assert data is None


@pytest.mark.asyncio
async def test_get_google_book_info_google_success():
    google_data = {
        'totalItems': 1,
        'items': [{'volumeInfo': {'title': 'T1', 'description': 'D1'}}],
    }
    with patch(
        'src.utils.apis._fetch_json', return_value=google_data
    ) as mock_fetch:
        result = await apis.get_google_book_info('123')
        assert result == {
            'title': 'T1',
            'description': 'D1',
            'cover_url': None,
        }
        assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_get_google_book_info_fallback_brasilapi():
    async def fake_fetch(url, headers=None):
        if 'googleapis' in url:
            return {'totalItems': 0}
        return {'title': 'BR Title', 'synopsis': 'BR Desc'}

    with patch('src.utils.apis._fetch_json', side_effect=fake_fetch):
        result = await apis.get_google_book_info('123')
        assert result == {
            'title': 'BR Title',
            'description': 'BR Desc',
            'cover_url': None,
        }


@pytest.mark.asyncio
async def test_get_google_book_info_both_fail():
    with patch('src.utils.apis._fetch_json', return_value=None):
        result = await apis.get_google_book_info('123')
        assert result == {}

    with patch('src.utils.apis._fetch_json', return_value={}):
        result = await apis.get_google_book_info('123')
        assert result == {}

    async def fake_fetch2(url, headers=None):
        if 'googleapis' in url:
            return {'totalItems': 0}
        return None

    with patch('src.utils.apis._fetch_json', side_effect=fake_fetch2):
        result = await apis.get_google_book_info('123')
        assert result == {}


@pytest.mark.asyncio
async def test_get_google_book_info_google_no_description():
    google_data = {
        'totalItems': 1,
        'items': [{'volumeInfo': {}}],
    }
    with patch('src.utils.apis._fetch_json', return_value=google_data):
        result = await apis.get_google_book_info('123')
        assert result == {
            'title': None,
            'description': None,
            'cover_url': None,
        }
