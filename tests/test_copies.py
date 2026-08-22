from http import HTTPStatus

import pytest

from scr.models import BookCondition, BooksStates, User, UserRole
from scr.schemas import BookCopyPublic
from scr.security import get_password_hash
from tests.factories import BookCopyFactory, BookFactory


def test_create_book_copy(client, token, book, user):
    book_id = book.id
    user_id = book.user_id

    response = client.post(
        f'/books/{book_id}/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'code': 'EX-0001',
            'state': 'available',
            'condition': 'new',
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data['book_id'] == book_id
    assert data['user_id'] == user_id
    assert data['school_id'] == user.school_id
    assert data['code'] == 'EX-0001'
    assert data['state'] == 'available'
    assert data['condition'] == 'new'


def test_create_book_copy_book_not_found(client, token):
    response = client.post(
        '/books/10/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={'code': 'EX-0002'},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Book not found.'}


@pytest.mark.asyncio
async def test_create_book_copy_duplicate_code(
    session, client, user, token, book
):
    book_id = book.id
    copy_code = BookCopyFactory.build(
        book_id=book_id, user_id=user.id, school_id=user.school_id
    ).code
    copy = BookCopyFactory(
        book_id=book_id,
        user_id=user.id,
        school_id=user.school_id,
        code=copy_code,
    )
    session.add(copy)
    await session.commit()

    response = client.post(
        f'/books/{book_id}/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={'code': copy_code},
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json() == {'detail': 'This Copy already exists'}


@pytest.mark.asyncio
async def test_create_book_copy_from_other_user_book(
    session, client, other_user, token
):
    book_other_user = BookFactory(user_id=other_user.id)
    session.add(book_other_user)
    await session.commit()
    await session.refresh(book_other_user)

    response = client.post(
        f'/books/{book_other_user.id}/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={'code': 'EX-0003'},
    )

    # RBAC: qualquer usuário de escola pode criar cópia
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['book_id'] == book_other_user.id


@pytest.mark.asyncio
async def test_list_copies_should_return_5_copies(
    session, client, user, token, book
):
    expected_copies = 5
    copies = BookCopyFactory.create_batch(
        expected_copies,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )

    session.add_all(copies)
    await session.commit()

    for copy in copies:
        await session.refresh(copy)

    expected_json = [
        BookCopyPublic.model_validate(c, from_attributes=True).model_dump(
            mode='json'
        )
        for c in copies
    ]

    response = client.get(
        '/copies/',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['copies']) == expected_copies
    assert response.json()['copies'] == expected_json


@pytest.mark.asyncio
async def test_list_copies_pagination_should_return_2_copies(
    session, client, user, token, book
):
    copies = BookCopyFactory.create_batch(
        5,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    expected_copies = 2

    session.add_all(copies)
    await session.commit()

    for copy in copies:
        await session.refresh(copy)

    expected_json = [
        BookCopyPublic.model_validate(c, from_attributes=True).model_dump(
            mode='json'
        )
        for c in copies[1:3]
    ]

    response = client.get(
        '/copies/?offset=1&limit=2',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert len(response.json()['copies']) == expected_copies
    assert response.json()['copies'] == expected_json


@pytest.mark.asyncio
async def test_list_copies_filter_state_should_return_5_copies(
    session, client, user, token, book
):
    expected_copies = 5
    copies = BookCopyFactory.create_batch(
        expected_copies,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    other_copies = BookCopyFactory.create_batch(
        expected_copies,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )

    session.add_all(copies + other_copies)
    await session.commit()

    for copy in copies:
        await session.refresh(copy)

    expected_json = [
        BookCopyPublic.model_validate(c, from_attributes=True).model_dump(
            mode='json'
        )
        for c in copies
    ]

    response = client.get(
        '/copies/?state=available',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['copies']) == expected_copies
    assert response.json()['copies'] == expected_json


@pytest.mark.asyncio
async def test_list_copies_filter_condition_should_return_5_copies(
    session, client, user, token, book
):
    expected_copies = 5
    copies = BookCopyFactory.create_batch(
        expected_copies,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    other_copies = BookCopyFactory.create_batch(
        expected_copies,
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        condition=BookCondition.POOR,
    )

    session.add_all(copies + other_copies)
    await session.commit()

    for copy in copies:
        await session.refresh(copy)

    expected_json = [
        BookCopyPublic.model_validate(c, from_attributes=True).model_dump(
            mode='json'
        )
        for c in copies
    ]

    response = client.get(
        '/copies/?condition=good',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['copies']) == expected_copies
    assert response.json()['copies'] == expected_json


@pytest.mark.asyncio
async def test_get_copy_by_id(session, client, user, token, book):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)

    response = client.get(
        f'/copies/{copy.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['code'] == copy.code


def test_get_copy_error(client, token):
    response = client.get(
        '/copies/10', headers={'Authorization': f'Bearer {token}'}
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Copy not found.'}


@pytest.mark.asyncio
async def test_patch_copy(session, client, user, token, book):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)

    response = client.patch(
        f'/copies/{copy.id}',
        headers={'Authorization': f'Bearer {token}'},
        json={'state': 'borrowed', 'notes': 'Emprestado para Maria'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['state'] == 'borrowed'
    assert response.json()['notes'] == 'Emprestado para Maria'


def test_patch_copy_error(client, token):
    response = client.patch(
        '/copies/10',
        headers={'Authorization': f'Bearer {token}'},
        json={},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Copy not found.'}


@pytest.mark.asyncio
async def test_delete_copy(session, client, user, token, book):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)

    response = client.delete(
        f'/copies/{copy.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        'message': 'Copy has been deleted successfully.'
    }


def test_delete_copy_error(client, token):
    response = client.delete(
        '/copies/10', headers={'Authorization': f'Bearer {token}'}
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {'detail': 'Copy not found.'}


@pytest.mark.asyncio
async def test_delete_book_cascades_copies(
    session, client, user, super_admin_token, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)

    response = client.delete(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert response.status_code == HTTPStatus.OK

    response = client.get(
        f'/copies/{copy.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_same_code_different_schools_allowed(
    session, client, user, book, other_school
):
    # same code "CODEX" in two different schools should succeed
    common_code = 'CODEX-001'

    token = client.post(
        '/auth/token',
        data={
            'username': user.username,
            'password': user.clean_password,
        },
    ).json()['access_token']

    # copy for user's school
    resp1 = client.post(
        f'/books/{book.id}/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={'code': common_code},
    )
    assert resp1.status_code == HTTPStatus.CREATED
    assert resp1.json()['code'] == common_code
    assert resp1.json()['school_id'] == user.school_id

    # create user in other_school
    other_user_pw = 'testteste'
    other_user2 = User(
        username='other_school_user_tmp',
        email='other_school_tmp@exemplo.com',
        password=get_password_hash(other_user_pw),
        role=UserRole.LIBRARIAN,
        school_id=other_school.id,
    )
    session.add(other_user2)
    await session.commit()
    await session.refresh(other_user2)

    other_token = client.post(
        '/auth/token',
        data={
            'username': other_user2.username,
            'password': other_user_pw,
        },
    ).json()['access_token']

    resp2 = client.post(
        f'/books/{book.id}/copies/',
        headers={'Authorization': f'Bearer {other_token}'},
        json={'code': common_code},
    )
    assert resp2.status_code == HTTPStatus.CREATED
    assert resp2.json()['code'] == common_code
    assert resp2.json()['school_id'] == other_school.id

    # same school duplicate should fail 409
    resp3 = client.post(
        f'/books/{book.id}/copies/',
        headers={'Authorization': f'Bearer {token}'},
        json={'code': common_code},
    )
    assert resp3.status_code == HTTPStatus.CONFLICT
