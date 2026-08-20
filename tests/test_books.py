from http import HTTPStatus

import pytest

from scr.models import BooksStates
from scr.schemas import BooksPublic
from tests.factories import BookFactory


def test_create_book(client, token):
    response = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'title': 'Test book',
            'description': 'Test book description',
            'state': 'available',
            'isbn': '978-3-16-148410-0',
            'internal_code': None,
        },
    )
    assert response.json() == {
        'id': 1,
        'title': 'Test book',
        'description': 'Test book description',
        'state': 'available',
        'isbn': '978-3-16-148410-0',
        'internal_code': None,
    }


@pytest.mark.asyncio
async def test_list_books_should_return_5_books(session, client, user, token):
    expected_books = 5
    books = BookFactory.create_batch(expected_books, user_id=user.id)

    session.add_all(books)
    await session.commit()

    for book in books:
        await session.refresh(book)

    expected_json = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books
    ]

    response = client.get(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['books']) == expected_books
    assert response.json()['books'] == expected_json


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

    expected_json = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books[1:3]
    ]

    response = client.get(
        '/books/?offset=1&limit=2',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['books']) == expected_books
    assert response.json()['books'] == expected_json


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

    for book in books:
        await session.refresh(book)

    expected_json = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books
    ]

    response = client.get(
        '/books/?title=Test book 1',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['books']) == expected_books
    assert response.json()['books'] == expected_json


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

    for book in books:
        await session.refresh(book)

    expected_json = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books
    ]

    response = client.get(
        '/books/?description=desc',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['books']) == expected_books
    assert response.json()['books'] == expected_json


@pytest.mark.asyncio
async def test_list_books_filter_state_should_return_5_books(
    session, user, client, token
):
    expected_books = 5
    books = BookFactory.create_batch(
        expected_books, user_id=user.id, state=BooksStates.AVAILABLE
    )
    other_books = BookFactory.create_batch(
        expected_books, user_id=user.id, state=BooksStates.ARCHIVED
    )

    session.add_all(books + other_books)
    await session.commit()

    for book in books:
        await session.refresh(book)

    expected_json = [
        BooksPublic.model_validate(t, from_attributes=True).model_dump(
            mode='json'
        )
        for t in books
    ]

    response = client.get(
        '/books/?state=available',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['books']) == expected_books
    assert response.json()['books'] == expected_json


def test_delete_book_error(client, token):
    response = client.delete(
        '/books/10', headers={'Authorization': f'Bearer {token}'}
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}


@pytest.mark.asyncio
async def test_delete_book(session, client, user, token):
    book = BookFactory(user_id=user.id)
    session.add(book)
    await session.commit()
    await session.refresh(book)

    response = client.delete(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        'message': 'Book has been deleted successfully.'
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

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}


@pytest.mark.asyncio
async def test_patch_book(session, client, user, token):
    book = BookFactory(user_id=user.id)

    session.add(book)
    await session.commit()
    await session.refresh(book)

    response = client.patch(
        f'/books/{book.id}',
        json={'title': 'teste!'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['title'] == 'teste!'


def test_patch_book_error(client, token):
    response = client.patch(
        '/books/10',
        json={},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}
