from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

import pytest
from jwt import decode, encode
from sqlalchemy import select, update

from src.models import User
from src.schemas import GuestBookPublic
from src.settings import Settings
from tests.factories import BookCopyFactory, BookFactory


def _auth(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_guest_access_token_has_ephemeral_minimal_claims(
    client, school, session
):
    response = client.post('/auth/guest', json={'school_code': school.code})

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['token_type'] == 'Bearer'
    assert 'refresh_token' not in body

    claims = decode(
        body['access_token'],
        Settings().SECRET_KEY,
        algorithms=[Settings().ALGORITHM],
    )
    assert claims['sub'] == 'guest'
    assert claims['role'] == 'guest'
    assert claims['type'] == 'guest'
    assert claims['school_code'] == school.code
    assert claims['exp'] > datetime.now(tz=ZoneInfo('UTC')).timestamp()
    for private_claim in ('cpf', 'email', 'name', 'user_id', 'id'):
        assert private_claim not in claims

    # The endpoint must not create a persisted Guest user.
    assert await session.scalar(select(User).where(User.username == 'guest')) is None


@pytest.mark.asyncio
async def test_guest_can_list_and_view_public_books(
    client, school, user, session
):
    book = BookFactory(
        title='Livro público para visitante', added_by=user.id
    )
    session.add(book)
    await session.commit()
    await session.refresh(book)

    copy = BookCopyFactory(
        book_id=book.id, school_id=school.id, added_by=user.id
    )
    session.add(copy)
    await session.commit()

    token_response = client.post(
        '/auth/guest', json={'school_code': school.code}
    )
    token = token_response.json()['access_token']

    listed = client.get('/books/', headers=_auth(token))
    assert listed.status_code == HTTPStatus.OK
    assert listed.json()['items']
    guest_book = listed.json()['items'][0]
    assert guest_book['id'] == book.id
    assert set(guest_book) == set(
        GuestBookPublic.model_fields
    ) | {'derived_state', 'total_copies', 'available_copies'}
    assert 'added_by' not in guest_book
    assert 'edited_by' not in guest_book

    detail = client.get(f'/books/{book.id}', headers=_auth(token))
    assert detail.status_code == HTTPStatus.OK
    assert detail.json()['id'] == book.id
    assert 'added_by' not in detail.json()
    assert 'edited_by' not in detail.json()


@pytest.mark.asyncio
async def test_guest_list_only_returns_books_openable_in_its_school(
    client, school, other_school, user, session
):
    visible = BookFactory(title='Livro visível', added_by=user.id)
    other_school_book = BookFactory(
        title='Livro de outra escola', added_by=user.id
    )
    orphan = BookFactory(title='Livro sem exemplar', added_by=user.id)
    session.add_all([visible, other_school_book, orphan])
    await session.commit()
    await session.refresh(visible)
    await session.refresh(other_school_book)

    session.add_all([
        BookCopyFactory(
            book_id=visible.id, school_id=school.id, added_by=user.id
        ),
        BookCopyFactory(
            book_id=other_school_book.id,
            school_id=other_school.id,
            added_by=user.id,
        ),
    ])
    await session.commit()

    token = client.post(
        '/auth/guest', json={'school_code': school.code}
    ).json()['access_token']
    listed = client.get('/books/', headers=_auth(token))

    assert listed.status_code == HTTPStatus.OK
    ids = [item['id'] for item in listed.json()['items']]
    assert visible.id in ids
    assert other_school_book.id not in ids
    assert orphan.id not in ids
    for book_id in ids:
        assert client.get(f'/books/{book_id}', headers=_auth(token)).status_code == HTTPStatus.OK


def test_guest_is_forbidden_from_private_and_admin_routes(
    client, school
):
    token_response = client.post(
        '/auth/guest', json={'school_code': school.code}
    )
    assert token_response.status_code == HTTPStatus.OK
    headers = _auth(token_response.json()['access_token'])

    requests = [
        ('get', '/users/'),
        ('get', '/schools/'),
        ('get', '/copies/'),
        ('get', '/loans/'),
        ('get', '/loans/me'),
        ('get', '/reservations/'),
        ('get', '/reservations/me'),
        ('get', '/books/lookup?isbn=9783161484100'),
        ('post', '/books/'),
    ]
    for method, path in requests:
        request = getattr(client, method)
        response = (
            request(path, headers=headers, json={})
            if method == 'post'
            else request(path, headers=headers)
        )
        assert response.status_code == HTTPStatus.FORBIDDEN, (
            method,
            path,
            response.text,
        )


def test_guest_expired_and_invalid_tokens_are_rejected(client, school):
    settings = Settings()
    expired = encode(
        {
            'sub': 'guest',
            'role': 'guest',
            'school_code': school.code,
            'type': 'guest',
            'exp': datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    expired_response = client.get('/books/', headers=_auth(expired))
    assert expired_response.status_code == HTTPStatus.UNAUTHORIZED

    invalid_response = client.get(
        '/books/', headers=_auth('not.a.valid.jwt')
    )
    assert invalid_response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_guest_token_for_inactive_or_unknown_school_is_rejected(
    client, school, session
):
    await session.execute(
        update(type(school)).where(type(school).id == school.id).values(
            is_active=False
        )
    )
    await session.commit()
    inactive = client.post('/auth/guest', json={'school_code': school.code})
    assert inactive.status_code == HTTPStatus.NOT_FOUND

    unknown = client.post('/auth/guest', json={'school_code': 'UNKNOWN'})
    assert unknown.status_code == HTTPStatus.NOT_FOUND
