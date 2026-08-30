from http import HTTPStatus

import pytest

from src.models import BooksStates
from src.schemas import BooksPublic
from tests.factories import BookCopyFactory, BookFactory


def _expected_books_json(books, derived_state='available'):
    """Serialize books as the API does, forcing the derived state.

    The API derives state from the school's copies; in these tests every
    expected book has exactly one AVAILABLE copy, so derived_state='available'.
    """
    out = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books
    ]
    for item in out:
        item['derived_state'] = derived_state
        if derived_state == 'available':
            item['total_copies'] = 1
            item['available_copies'] = 1
        elif derived_state in {'borrowed', 'reserved', 'lost'}:
            item['total_copies'] = 1
            item['available_copies'] = 0
        else:
            item['total_copies'] = 0
            item['available_copies'] = 0
    return out


def test_create_book(client, token):
    response = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'title': 'Test book',
            'description': 'Test book description',
            'isbn': '978-3-16-148410-0',
        },
    )
    data = response.json()
    assert data['id'] == 1
    assert data['title'] == 'Test book'
    assert data['description'] == 'Test book description'
    assert data['derived_state'] == 'archived'
    assert data['isbn'] == '9783161484100'
    assert data['is_active'] is True
    assert 'added_by' in data
    assert 'edited_by' in data


def test_create_book_error_missing_title(client, token):
    # neither title nor isbn -> 422 from schema validation
    response = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'description': None,
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_create_book_without_description_should_return_none(client, token):
    response = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'title': 'Livro sem descrição',
            'description': None,
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['description'] is None
    assert 'Sem descrição' not in (response.json()['description'] or '')


def test_create_book_duplicate_isbn(client, token):
    book_data = {
        'title': 'Livro duplicado',
        'isbn': '978-0-00-000001-1',
    }

    first = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json=book_data,
    )
    assert first.status_code == HTTPStatus.CREATED

    second = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json=book_data,
    )
    assert second.status_code == HTTPStatus.CONFLICT
    assert second.json() == {'detail': 'This Book already exists'}


@pytest.mark.asyncio
async def test_list_books_should_return_5_books(session, client, user, token):
    expected_books = 5
    books = BookFactory.create_batch(expected_books, user_id=user.id)

    session.add_all(books)
    await session.commit()

    for book in books:
        await session.refresh(book)

    expected_json = _expected_books_json(books)

    # Tenant isolation: list_books filters by BookCopy.school_id
    copies = [
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=user.school_id
        )
        for book in books
    ]
    session.add_all(copies)
    await session.commit()

    response = client.get(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['items']) == expected_books
    assert response.json()['items'] == expected_json


@pytest.mark.asyncio
async def test_list_books_pagination_should_return_2_books(
    session, user, client, token
):
    books = BookFactory.create_batch(5, user_id=user.id)
    expected_books = 2

    session.add_all(books)
    await session.commit()

    for book in books:
        await session.refresh(book)

    expected_json = _expected_books_json(books[1:3])

    copies = [
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=user.school_id
        )
        for book in books
    ]
    session.add_all(copies)
    await session.commit()

    response = client.get(
        '/books/?offset=1&limit=2',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['items']) == expected_books
    assert response.json()['items'] == expected_json


@pytest.mark.asyncio
async def test_list_books_filter_title_should_return_5_books(
    session, user, client, token
):
    expected_books = 5
    books = BookFactory.create_batch(
        expected_books, user_id=user.id, title='Test book 1'
    )
    other_books = BookFactory.create_batch(
        expected_books, user_id=user.id, title='Test book 2'
    )

    session.add_all(books + other_books)
    await session.commit()

    for book in books + other_books:
        await session.refresh(book)

    expected_json = _expected_books_json(books)

    # copies for all books so tenant filter passes
    all_books = books + other_books
    copies = [
        BookCopyFactory(
            book_id=b.id, user_id=user.id, school_id=user.school_id
        )
        for b in all_books
    ]
    session.add_all(copies)
    await session.commit()

    response = client.get(
        '/books/?title=Test book 1',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['items']) == expected_books
    assert response.json()['items'] == expected_json


@pytest.mark.asyncio
async def test_list_books_filter_description_should_return_5_books(
    session, user, client, token
):
    expected_books = 5
    books = BookFactory.create_batch(
        expected_books, user_id=user.id, description='description'
    )
    other_books = BookFactory.create_batch(
        expected_books, user_id=user.id, description='Test book'
    )

    session.add_all(books + other_books)
    await session.commit()

    for book in books + other_books:
        await session.refresh(book)

    expected_json = _expected_books_json(books)

    all_books = books + other_books
    copies = [
        BookCopyFactory(
            book_id=b.id, user_id=user.id, school_id=user.school_id
        )
        for b in all_books
    ]
    session.add_all(copies)
    await session.commit()

    response = client.get(
        '/books/?description=desc',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['items']) == expected_books
    assert response.json()['items'] == expected_json


@pytest.mark.asyncio
async def test_list_books_filter_state_should_return_available_books(
    session, user, client, token
):
    # available: has at least one AVAILABLE copy in the user's school
    avail_books = BookFactory.create_batch(2, user_id=user.id)
    # borrowed: has copies but none available
    borrowed_books = BookFactory.create_batch(2, user_id=user.id)
    # none: no copies in the user's school
    no_copy_book = BookFactory.create_batch(1, user_id=user.id)

    all_books = avail_books + borrowed_books + no_copy_book
    session.add_all(all_books)
    await session.commit()
    for book in all_books:
        await session.refresh(book)

    available_copies = [
        BookCopyFactory(
            book_id=b.id, user_id=user.id, school_id=user.school_id
        )
        for b in avail_books
    ]
    borrowed_copies = [
        BookCopyFactory(
            book_id=b.id,
            user_id=user.id,
            school_id=user.school_id,
            state=BooksStates.BORROWED,
        )
        for b in borrowed_books
    ]
    session.add_all(available_copies + borrowed_copies)
    await session.commit()

    response = client.get(
        '/books/?state=available',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    ids = [item['id'] for item in response.json()['items']]
    assert sorted(ids) == sorted(b.id for b in avail_books)
    for item in response.json()['items']:
        assert item['derived_state'] == 'available'


@pytest.mark.asyncio
async def test_list_books_filter_state_should_return_borrowed_books(
    session, user, client, token
):
    avail_books = BookFactory.create_batch(1, user_id=user.id)
    borrowed_books = BookFactory.create_batch(2, user_id=user.id)

    session.add_all(avail_books + borrowed_books)
    await session.commit()
    for book in avail_books + borrowed_books:
        await session.refresh(book)

    session.add_all(
        [
            BookCopyFactory(
                book_id=b.id, user_id=user.id, school_id=user.school_id
            )
            for b in avail_books
        ]
        + [
            BookCopyFactory(
                book_id=b.id,
                user_id=user.id,
                school_id=user.school_id,
                state=BooksStates.BORROWED,
            )
            for b in borrowed_books
        ]
    )
    await session.commit()

    response = client.get(
        '/books/?state=borrowed',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    ids = [item['id'] for item in response.json()['items']]
    assert sorted(ids) == sorted(b.id for b in borrowed_books)
    for item in response.json()['items']:
        assert item['derived_state'] == 'borrowed'


def test_delete_book_error(client, super_admin_token):
    response = client.delete(
        '/books/10',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}


@pytest.mark.asyncio
async def test_delete_book(session, client, super_admin, super_admin_token):
    book = BookFactory(user_id=super_admin.id)
    session.add(book)
    await session.commit()
    await session.refresh(book)

    response = client.delete(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        'message': 'Book has been deactivated successfully.'
    }


@pytest.mark.asyncio
async def test_delete_book_from_other_user(
    session, client, user, other_user, token
):
    book_other_user = BookFactory(user_id=other_user.id)
    session.add(book_other_user)
    await session.commit()
    await session.refresh(book_other_user)

    response = client.delete(
        f'/books/{book_other_user.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    # RBAC: only SUPER_ADMIN can delete, librarian gets 403
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json() == {'detail': 'Not enough permissions'}


@pytest.mark.asyncio
async def test_patch_book(session, client, super_admin, super_admin_token):
    book = BookFactory(user_id=super_admin.id)

    session.add(book)
    await session.commit()
    await session.refresh(book)

    response = client.patch(
        f'/books/{book.id}',
        json={'title': 'teste!'},
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['title'] == 'teste!'


def test_patch_book_error(client, super_admin_token):
    response = client.patch(
        '/books/10',
        json={},
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}


def test_create_book_integrity_error_mock(client, token, monkeypatch):  # noqa: ARG001
    # Use patch on session object via dependency override is easier: directly test route via mock
    # Simulate by patching AsyncSession.commit globally not available, so use client dependency override approach:
    # Instead verify branch via mocking session.commit on the session instance returned by get_session
    # Easiest: call route directly with mocked session
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.exc import IntegrityError

    from src.routers.books import create_book
    from src.schemas import BooksSchema

    mock_session = AsyncMock()
    mock_session.commit.side_effect = IntegrityError('statement', {}, None)
    mock_session.rollback = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.refresh = AsyncMock()

    # need a mock user with allowed role
    from src.models import User, UserRole

    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.role = UserRole.LIBRARIAN
    mock_user.school_id = 1

    # also mock scalar for isbn check to return None and google api
    mock_session.scalar = AsyncMock(return_value=None)

    async def run():
        from unittest.mock import patch

        with patch(
            'src.routers.books.get_google_book_info', new_callable=AsyncMock
        ) as mock_google:
            mock_google.return_value = {}
            try:
                await create_book(
                    BooksSchema(
                        title='Test Integrity', isbn='978-0-00-000001-9'
                    ),
                    mock_session,
                    mock_user,
                )
            except Exception as e:
                from fastapi import HTTPException

                assert isinstance(e, HTTPException)
                assert e.status_code == HTTPStatus.CONFLICT
                return
            assert False, 'should have raised'

    asyncio.run(run())


def test_super_admin_cannot_create_copy(client, super_admin_token, book):
    resp = client.post(
        f'/books/{book.id}/copies/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'code': 'EX-SUPER-1'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN
    assert resp.json()['detail'] == 'SUPER_ADMIN cannot create copies'


def test_create_copy_integrity_error_mock():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from src.models import User, UserRole
    from src.routers.books import create_book_copy
    from src.schemas import BookCopySchema

    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock()

    # first scalar for book exists, second for existing_copy None, then commit raises
    async def scalar_side_effect(query):
        # book query returns a book

        # Use string check: if Book in query, return mock book
        qstr = str(query)
        if 'books' in qstr.lower() or 'book' in qstr.lower():
            # first call is book lookup, return mock book; second is existing_copy check return None
            # need stateful
            if not hasattr(scalar_side_effect, 'calls'):
                scalar_side_effect.calls = 0
            scalar_side_effect.calls += 1
            if scalar_side_effect.calls == 1:
                m = MagicMock()
                m.id = 1
                return m
            return None
        return None

    mock_session.scalar.side_effect = scalar_side_effect
    mock_session.commit = AsyncMock(
        side_effect=IntegrityError('stmt', {}, None)
    )
    mock_session.rollback = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.refresh = AsyncMock()

    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.role = UserRole.LIBRARIAN
    mock_user.school_id = 1

    async def run():
        try:
            await create_book_copy(
                1, BookCopySchema(code='EX-INT-1'), mock_session, mock_user
            )
        except HTTPException as e:
            assert e.status_code == HTTPStatus.CONFLICT
            return
        assert False

    asyncio.run(run())


def test_create_copy_without_school_via_override(
    client, book, super_admin_token, school
):
    # Use dependency override to simulate user without school
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake_user = User(
        username='noschool_lib',
        email='noschool@ex.com',
        password='hashed',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake_user.id = 9999

    async def fake_get_current_user():
        return fake_user

    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        resp = client.post(
            f'/books/{book.id}/copies/',
            headers={'Authorization': 'Bearer fake'},
            json={'code': 'EX-NOSCHOOL'},
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
        assert 'without school' in resp.json()['detail']
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_books_is_active_filter(session, client, user, token):
    # create one active and one inactive book
    active_book = BookFactory(user_id=user.id, is_active=True)
    inactive_book = BookFactory(user_id=user.id, is_active=False)
    session.add_all([active_book, inactive_book])
    await session.commit()
    await session.refresh(active_book)
    await session.refresh(inactive_book)
    # copies for tenant filter
    for b in [active_book, inactive_book]:
        c = BookCopyFactory(
            book_id=b.id, user_id=user.id, school_id=user.school_id
        )
        session.add(c)
    await session.commit()
    # default should only return active
    resp = client.get('/books/', headers={'Authorization': f'Bearer {token}'})
    ids = [x['id'] for x in resp.json()['items']]
    assert active_book.id in ids
    assert inactive_book.id not in ids
    # explicit false
    resp2 = client.get(
        '/books/?is_active=false', headers={'Authorization': f'Bearer {token}'}
    )
    ids2 = [x['id'] for x in resp2.json()['items']]
    assert inactive_book.id in ids2
    assert active_book.id not in ids2
    # explicit true
    resp3 = client.get(
        '/books/?is_active=true', headers={'Authorization': f'Bearer {token}'}
    )
    ids3 = [x['id'] for x in resp3.json()['items']]
    assert active_book.id in ids3


def test_list_books_without_school_forbidden(client, book):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake_user = User(
        username='noschool2',
        email='noschool2@ex.com',
        password='hashed',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake_user.id = 9998

    async def fake():
        return fake_user

    app.dependency_overrides[get_current_user] = fake
    try:
        resp = client.get('/books/', headers={'Authorization': 'Bearer fake'})
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


def test_patch_book_forbidden_for_teacher(client, teacher_token, book):
    resp = client.patch(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {teacher_token}'},
        json={'title': 'hacked'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


# ---------------------------------------------------------------------------
# coverage: /books/lookup
# ---------------------------------------------------------------------------
def test_lookup_book_short_isbn(client, token):
    resp = client.get(
        '/books/lookup?isbn=1234',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_lookup_book_existing(session, client, user, token):
    book = BookFactory(user_id=user.id, isbn='978-3-16-148410-0')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/lookup?isbn=978-3-16-148410-0',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data['found'] is True
    assert data['already_exists'] is True
    assert data['existing_book_id'] == book.id
    assert data['isbn'] == '9783161484100'


@pytest.mark.asyncio
async def test_lookup_book_normalized_fallback(session, client, user, token):
    book = BookFactory(user_id=user.id, isbn='978-3-16-148410-0')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/lookup?isbn=9783161484100',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['already_exists'] is True


@pytest.mark.asyncio
async def test_lookup_book_via_google(session, client, user, token):
    from unittest.mock import AsyncMock, patch

    with patch(
        'src.routers.books.get_google_book_info', new_callable=AsyncMock
    ) as mock_google:
        mock_google.return_value = {
            'title': 'Novo Livro',
            'description': 'Desc',
            'cover_url': None,
        }
        resp = client.get(
            '/books/lookup?isbn=9780000000011',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data['found'] is True
    assert data['already_exists'] is False
    assert data['title'] == 'Novo Livro'


@pytest.mark.asyncio
async def test_lookup_book_not_found(session, client, user, token):
    from unittest.mock import AsyncMock, patch

    with patch(
        'src.routers.books.get_google_book_info', new_callable=AsyncMock
    ) as mock_google:
        mock_google.return_value = {}
        resp = client.get(
            '/books/lookup?isbn=9780000000012',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['found'] is False
    assert resp.json()['title'] is None


# ---------------------------------------------------------------------------
# coverage: /books/resolve
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_book_by_isbn_direct(session, client, user, token):
    book = BookFactory(user_id=user.id, isbn='9783161484100')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/resolve?term=9783161484100',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'kind': 'isbn', 'book_id': book.id}


@pytest.mark.asyncio
async def test_resolve_book_by_isbn_normalized(session, client, user, token):
    book = BookFactory(user_id=user.id, isbn='978-3-16-148410-0')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/resolve?term=9783161484100',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'kind': 'isbn', 'book_id': book.id}


@pytest.mark.asyncio
async def test_resolve_book_isbn_not_found(session, client, user, token):
    resp = client.get(
        '/books/resolve?term=9780000000012',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'kind': 'none', 'book_id': None}


@pytest.mark.asyncio
async def test_resolve_book_internal_code(session, client, user, token):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id,
            user_id=user.id,
            school_id=user.school_id,
            code='INT-1',
        )
    )
    await session.commit()

    resp = client.get(
        '/books/resolve?term=INT-1',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'kind': 'internal_code', 'book_id': book.id}


@pytest.mark.asyncio
async def test_resolve_book_title(session, client, user, token):
    resp = client.get(
        '/books/resolve?term=algum-titulo',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'kind': 'title', 'book_id': None}


def test_resolve_book_without_school_forbidden(client, book):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake_user = User(
        username='noschool3',
        email='noschool3@ex.com',
        password='h',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake_user.id = 9997

    async def fake():
        return fake_user

    app.dependency_overrides[get_current_user] = fake
    try:
        resp = client.get(
            '/books/resolve?term=titulo-x',
            headers={'Authorization': 'Bearer fake'},
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# coverage: /books/suggest
# ---------------------------------------------------------------------------
def test_suggest_books_empty_q(client, token):
    resp = client.get(
        '/books/suggest?q=',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {'items': []}


@pytest.mark.asyncio
async def test_suggest_books(session, client, user, token):
    book = BookFactory(user_id=user.id, title='Dom Casmurro')
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=user.school_id
        )
    )
    await session.commit()

    resp = client.get(
        '/books/suggest?q=Casmurro',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert [i['id'] for i in resp.json()['items']] == [book.id]


@pytest.mark.asyncio
async def test_suggest_books_super_admin(
    session, client, super_admin, super_admin_token
):
    book = BookFactory(user_id=super_admin.id, title='Postumas Book')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/suggest?q=Postumas',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert [i['id'] for i in resp.json()['items']] == [book.id]


def test_suggest_books_without_school_forbidden(client, book):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake_user = User(
        username='noschool4',
        email='noschool4@ex.com',
        password='h',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake_user.id = 9996

    async def fake():
        return fake_user

    app.dependency_overrides[get_current_user] = fake
    try:
        resp = client.get(
            '/books/suggest?q=Qualquer',
            headers={'Authorization': 'Bearer fake'},
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# coverage: create_book edge cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_book_duplicate_normalized_isbn(
    session, client, user, token
):
    book = BookFactory(user_id=user.id, isbn='978-0-00-000001-1')
    session.add(book)
    await session.commit()

    resp = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={'isbn': '9780000000011', 'title': 'X'},
    )
    assert resp.status_code == HTTPStatus.CONFLICT
    assert resp.json() == {'detail': 'This Book already exists'}


def test_create_book_isbn_info_not_found(client, token):
    from unittest.mock import AsyncMock, patch

    with patch(
        'src.routers.books.get_google_book_info', new_callable=AsyncMock
    ) as mock_google:
        mock_google.return_value = {}
        resp = client.post(
            '/books/',
            headers={'Authorization': f'Bearer {token}'},
            json={'isbn': '9780000000012'},
        )

    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert resp.json()['detail'] == 'Book information not found'


# ---------------------------------------------------------------------------
# coverage: list_books filters (q, isbn, internal_code)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_books_filter_q_internal_code(session, client, user, token):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id,
            user_id=user.id,
            school_id=user.school_id,
            code='EX-C1',
        )
    )
    await session.commit()

    resp = client.get(
        '/books/?q=EX-C1',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert book.id in [x['id'] for x in resp.json()['items']]


@pytest.mark.asyncio
async def test_list_books_filter_q_super_admin(
    session, client, super_admin, super_admin_token
):
    book = BookFactory(user_id=super_admin.id, title='QFilter')
    session.add(book)
    await session.commit()

    resp = client.get(
        '/books/?q=QFilter',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert book.id in [x['id'] for x in resp.json()['items']]


@pytest.mark.asyncio
async def test_list_books_filter_isbn(session, client, user, token):
    book = BookFactory(user_id=user.id, isbn='9780000000011')
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=user.school_id
        )
    )
    await session.commit()

    resp = client.get(
        '/books/?isbn=978-0-00-000001-1',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert book.id in [x['id'] for x in resp.json()['items']]


@pytest.mark.asyncio
async def test_list_books_filter_internal_code(session, client, user, token):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id,
            user_id=user.id,
            school_id=user.school_id,
            code='PATR-100',
        )
    )
    await session.commit()

    resp = client.get(
        '/books/?internal_code=PATR-100',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert book.id in [x['id'] for x in resp.json()['items']]


# ---------------------------------------------------------------------------
# coverage: GET /books/{book_id}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_book_success(session, client, user, token):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=user.school_id
        )
    )
    await session.commit()

    resp = client.get(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['id'] == book.id
    assert resp.json()['derived_state'] == 'available'


def test_get_book_not_found(client, token):
    resp = client.get(
        '/books/99999',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_get_book_without_school_forbidden(client, book):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake_user = User(
        username='noschool5',
        email='noschool5@ex.com',
        password='h',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake_user.id = 9995

    async def fake():
        return fake_user

    app.dependency_overrides[get_current_user] = fake
    try:
        resp = client.get(
            f'/books/{book.id}',
            headers={'Authorization': 'Bearer fake'},
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_book_not_in_school(
    session, client, user, token, other_school
):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    session.add(
        BookCopyFactory(
            book_id=book.id, user_id=user.id, school_id=other_school.id
        )
    )
    await session.commit()

    resp = client.get(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND
