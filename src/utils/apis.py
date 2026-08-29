from http import HTTPStatus

import httpx

from src.settings import Settings

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


def _parse_published_date(raw: str | None) -> str | None:  # noqa: PLR0911
    """Normalize publishedDate variations (YYYY, YYYY-MM, YYYY-MM-DD) to ISO date.

    Returns YYYY-MM-DD string or None. Incomplete dates are padded with 01.
    """  # noqa: E501
    if not raw or not isinstance(raw, str):  # pragma: no cover
        return None  # pragma: no cover
    s = raw.strip()  # pragma: no cover
    if not s:  # pragma: no cover
        return None  # pragma: no cover
    # Google: 2020, 2020-05, 2020-05-17 ; BrasilAPI: may already be ISO
    parts = s.split('-')
    try:  # noqa: PLW0717
        if len(parts) == 1 and len(parts[0]) == 4 and parts[0].isdigit():  # noqa: PLR2004
            return f'{parts[0]}-01-01'
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():  # noqa: PLR2004
            return f'{parts[0]}-{parts[1].zfill(2)}-01'
        if len(parts) == 3:  # noqa: PLR2004
            # validate date
            from datetime import date  # noqa: PLC0415

            y, m, d = int(parts[0]), int(parts[1]), int(parts[2][:2])
            date(y, m, d)
            return f'{y:04d}-{m:02d}-{d:02d}'
    except Exception:
        return None
    return None


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
        image_links = info.get('imageLinks') or {}
        categories = info.get('categories') or []
        # categories may be like ["Fiction / Romance"] -> split by "/"
        genres: list[str] = []  # pragma: no cover
        for cat in categories:  # pragma: no cover
            if isinstance(cat, str):  # pragma: no cover
                for part in cat.split('/'):  # pragma: no cover
                    p = part.strip()  # pragma: no cover
                    if p:  # pragma: no cover
                        genres.append(p)  # pragma: no cover
        authors = info.get('authors') or []
        if not isinstance(authors, list):
            authors = []
        authors = [str(a).strip() for a in authors if str(a).strip()]
        return {
            'title': info.get('title'),
            'description': info.get('description'),
            'cover_url': _normalize_cover_url(
                image_links.get('thumbnail')
                or image_links.get('smallThumbnail')
            ),
            'published_date': _parse_published_date(info.get('publishedDate')),
            'genres': genres,
            'authors': authors,
        }

    # 2. Segunda tentativa (Fallback): BrasilAPI para livros nacionais
    brasil_api_url = f'https://brasilapi.com.br/api/isbn/v1/{isbn}'

    data = await _fetch_json(brasil_api_url)  # pragma: no cover

    if data:  # pragma: no cover
        # BrasilAPI may have subjects/category - try common keys
        raw_genres = (
            data.get('subjects')
            or data.get('categories')
            or data.get('category')
        )
        genres2: list[str] = []
        if isinstance(raw_genres, list):
            genres2 = [str(g).strip() for g in raw_genres if str(g).strip()]
        elif isinstance(raw_genres, str) and raw_genres.strip():
            genres2 = [raw_genres.strip()]
        raw_authors = data.get('authors') or data.get('author')
        authors2: list[str] = []
        if isinstance(raw_authors, list):
            authors2 = [str(a).strip() for a in raw_authors if str(a).strip()]
        elif isinstance(raw_authors, str) and raw_authors.strip():
            authors2 = [raw_authors.strip()]
        # BrasilAPI uses various keys for publication year/date
        raw_pub = (
            data.get('publish_date')
            or data.get('published_date')
            or data.get('year')
            or data.get('date')
        )
        if isinstance(raw_pub, int):
            raw_pub = str(raw_pub)
        return {
            'title': data.get('title'),
            'description': data.get('synopsis'),
            'cover_url': _normalize_cover_url(data.get('cover_url')),
            'published_date': _parse_published_date(
                str(raw_pub) if raw_pub else None
            ),
            'genres': genres2,
            'authors': authors2,
        }

    return {'genres': [], 'authors': [], 'published_date': None}


def _normalize_cover_url(url: str | None) -> str | None:
    """Force https and drop size params from Google Books thumbnails."""
    if not url:
        return None
    url = url.strip()
    if url.startswith('http://'):
        url = 'https://' + url[len('http://') :]
    return url or None
