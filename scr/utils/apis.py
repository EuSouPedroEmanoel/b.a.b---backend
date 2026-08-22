from http import HTTPStatus

import httpx

from scr.settings import Settings

settings = Settings()

TIMEOUT = 4.0


async def _fetch_json(url: str, headers: dict | None = None) -> dict | None:
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=headers)
    except Exception:
        return None

    if response.status_code != HTTPStatus.OK:
        return None

    return response.json()


async def get_google_book_info(isbn: str) -> dict:
    # 1. Primeira tentativa: Google Books
    google_url = (
        'https://www.googleapis.com/books/v1/volumes'
        f'?q=isbn:{isbn}&key={settings.GOOGLE_BOOKS_API_KEY}'
    )
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}

    data = await _fetch_json(google_url, headers)

    if data and data.get('totalItems', 0) > 0:
        info = data['items'][0]['volumeInfo']
        return {
            'title': info.get('title'),
            'description': info.get('description'),
        }

    # 2. Segunda tentativa (Fallback): BrasilAPI para livros nacionais
    brasil_api_url = f'https://brasilapi.com.br/api/isbn/v1/{isbn}'

    data = await _fetch_json(brasil_api_url)

    if data:
        return {
            'title': data.get('title'),
            'description': data.get('synopsis'),
        }

    return {}
