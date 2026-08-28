from http import HTTPStatus

import pytest

from src.models import BooksStates
from tests.factories import BookCopyFactory


@pytest.mark.asyncio
async def test_create_reservation_success(
    session, client, user, token, student, teacher, book
):
    # make all copies borrowed so reservation is needed
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']

    resp = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert resp.json()['book_id'] == book.id
    assert resp.json()['user_id'] == student.id
    assert resp.json()['status'] == 'active'


@pytest.mark.asyncio
async def test_create_reservation_when_available_fails(
    session, client, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.AVAILABLE,
    )
    session.add(copy)
    await session.commit()

    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']

    resp = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert resp.status_code == HTTPStatus.CONFLICT


def test_create_reservation_forbidden_for_librarian(client, token, book):
    resp = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {token}'},
        json={'book_id': book.id},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_reservation_duplicate_fails(
    session, client, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']

    first = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert first.status_code == HTTPStatus.CREATED

    second = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert second.status_code == HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_cancel_reservation(session, client, user, student, book):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']

    first = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    rid = first.json()['id']

    resp = client.delete(
        f'/reservations/{rid}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert 'cancelled' in resp.json()['message'].lower()


@pytest.mark.asyncio
async def test_list_reservations_pagination(
    session, client, user, student, book
):
    # create borrowed copy so reservations allowed
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']

    # need multiple books for multiple reservations (same book duplicate not allowed if active)
    # create 3 books
    from tests.factories import BookFactory

    books = []
    for i in range(3):
        b = BookFactory(user_id=user.id)
        session.add(b)
        await session.commit()
        await session.refresh(b)
        # add borrowed copy for each
        c = BookCopyFactory(
            book_id=b.id,
            user_id=user.id,
            school_id=user.school_id,
            state=BooksStates.BORROWED,
            code=f'RC-{i}',
        )
        session.add(c)
        await session.commit()
        books.append(b)

    for b in books:
        client.post(
            '/reservations/',
            headers={'Authorization': f'Bearer {student_token}'},
            json={'book_id': b.id},
        )

    resp = client.get(
        '/reservations/me?page=1&size=2',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] >= 3
    assert resp.json()['size'] == 2
    assert len(resp.json()['items']) == 2


def test_create_reservation_without_school_forbidden(client, book):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake = User(
        username='noschool_res',
        email='noschool_res@ex.com',
        password='h',
        role=UserRole.STUDENT,
        school_id=None,
        is_active=True,
    )
    fake.id = 9992

    async def fake_user():
        return fake

    app.dependency_overrides[get_current_user] = fake_user
    try:
        resp = client.post(
            '/reservations/',
            headers={'Authorization': 'Bearer fake'},
            json={'book_id': book.id},
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


def test_create_reservation_book_not_found(client, student):
    token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    resp = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {token}'},
        json={'book_id': 99999},
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_create_reservation_book_inactive(
    session, client, student, book, super_admin_token
):
    # deactivate book via super_admin
    resp = client.delete(
        f'/books/{book.id}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    resp2 = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': book.id},
    )
    assert resp2.status_code == HTTPStatus.BAD_REQUEST
    assert 'inactive' in resp2.json()['detail'].lower()


@pytest.mark.asyncio
async def test_list_reservations_filters(
    session, client, user, student, teacher, book
):
    # create borrowed copy so reservations allowed
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    # create two reservations for different books
    from tests.factories import BookFactory

    books = []
    for i in range(2):
        b = BookFactory(user_id=user.id)
        session.add(b)
        await session.commit()
        await session.refresh(b)
        c = BookCopyFactory(
            book_id=b.id,
            user_id=user.id,
            school_id=user.school_id,
            state=BooksStates.BORROWED,
            code=f'RC-FILT-{i}',
        )
        session.add(c)
        await session.commit()
        books.append(b)
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    teacher_token = client.post(
        '/auth/token',
        data={
            'username': teacher.username,
            'password': teacher.clean_password,
        },
    ).json()['access_token']
    # student creates reservation for books[0]
    r1 = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': books[0].id},
    )
    assert r1.status_code == HTTPStatus.CREATED
    # teacher creates for books[1] but need borrowed copy already, so ok
    r2 = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {teacher_token}'},
        json={'book_id': books[1].id},
    )
    assert r2.status_code == HTTPStatus.CREATED
    # student list should only see own
    resp = client.get(
        '/reservations/', headers={'Authorization': f'Bearer {student_token}'}
    )
    assert resp.status_code == HTTPStatus.OK
    assert all(x['user_id'] == student.id for x in resp.json()['items'])
    # super_admin sees all (skipped, requires fixture)
    # librarian sees school scoped
    lib_token = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    ).json()['access_token']
    resp_lib = client.get(
        '/reservations/', headers={'Authorization': f'Bearer {lib_token}'}
    )
    assert resp_lib.status_code == HTTPStatus.OK
    assert resp_lib.json()['total'] >= 2
    # filter by status
    resp_status = client.get(
        '/reservations/?status=active',
        headers={'Authorization': f'Bearer {lib_token}'},
    )
    assert resp_status.status_code == HTTPStatus.OK
    # filter by book_id
    resp_book = client.get(
        f'/reservations/?book_id={books[0].id}',
        headers={'Authorization': f'Bearer {lib_token}'},
    )
    assert resp_book.status_code == HTTPStatus.OK
    assert all(x['book_id'] == books[0].id for x in resp_book.json()['items'])


def test_list_reservations_without_school_forbidden(client):
    from src.app import app
    from src.models import User, UserRole
    from src.security import get_current_user

    fake = User(
        username='noschool_res_list',
        email='noschool_res_list@ex.com',
        password='h',
        role=UserRole.LIBRARIAN,
        school_id=None,
        is_active=True,
    )
    fake.id = 9991

    async def fake_user():
        return fake

    app.dependency_overrides[get_current_user] = fake_user
    try:
        resp = client.get(
            '/reservations/', headers={'Authorization': 'Bearer fake'}
        )
        assert resp.status_code == HTTPStatus.FORBIDDEN
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_my_reservations_filters(
    session, client, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    from tests.factories import BookFactory

    b1 = BookFactory(user_id=user.id)
    session.add(b1)
    await session.commit()
    await session.refresh(b1)
    c1 = BookCopyFactory(
        book_id=b1.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='RC-MY-1',
    )
    session.add(c1)
    await session.commit()
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    r = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': b1.id},
    )
    assert r.status_code == HTTPStatus.CREATED
    # filter by status
    resp = client.get(
        '/reservations/me?status=active',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert all(x['status'] == 'active' for x in resp.json()['items'])
    # filter by book_id
    resp2 = client.get(
        f'/reservations/me?book_id={b1.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp2.status_code == HTTPStatus.OK
    assert all(x['book_id'] == b1.id for x in resp2.json()['items'])


def test_cancel_reservation_not_found(client, student):
    token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    resp = client.delete(
        '/reservations/99999', headers={'Authorization': f'Bearer {token}'}
    )
    assert resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_reservation_forbidden(
    client, session, user, student, teacher, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    from tests.factories import BookFactory

    b = BookFactory(user_id=user.id)
    session.add(b)
    await session.commit()
    await session.refresh(b)
    c = BookCopyFactory(
        book_id=b.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='RC-FORB-1',
    )
    session.add(c)
    await session.commit()
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    r = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': b.id},
    )
    rid = r.json()['id']
    # teacher same school but not owner and not librarian/school_admin -> should be forbidden (teacher role)
    teacher_token = client.post(
        '/auth/token',
        data={
            'username': teacher.username,
            'password': teacher.clean_password,
        },
    ).json()['access_token']
    resp = client.delete(
        f'/reservations/{rid}',
        headers={'Authorization': f'Bearer {teacher_token}'},
    )
    assert resp.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_cancel_reservation_not_active(
    session, client, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    from tests.factories import BookFactory

    b = BookFactory(user_id=user.id)
    session.add(b)
    await session.commit()
    await session.refresh(b)
    c = BookCopyFactory(
        book_id=b.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='RC-NACT-1',
    )
    session.add(c)
    await session.commit()
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    r = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': b.id},
    )
    rid = r.json()['id']
    # first cancel
    resp1 = client.delete(
        f'/reservations/{rid}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp1.status_code == HTTPStatus.OK
    # second cancel should be 409
    resp2 = client.delete(
        f'/reservations/{rid}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp2.status_code == HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_staff_can_cancel_reservation(
    session, client, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    from tests.factories import BookFactory

    b = BookFactory(user_id=user.id)
    session.add(b)
    await session.commit()
    await session.refresh(b)
    c = BookCopyFactory(
        book_id=b.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='RC-STAFF-1',
    )
    session.add(c)
    await session.commit()
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    r = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': b.id},
    )
    rid = r.json()['id']
    # librarian cancels
    lib_token = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    ).json()['access_token']
    resp = client.delete(
        f'/reservations/{rid}',
        headers={'Authorization': f'Bearer {lib_token}'},
    )
    assert resp.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_list_reservations_super_admin(
    session, client, super_admin_token, user, student, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()
    from tests.factories import BookFactory

    b = BookFactory(user_id=user.id)
    session.add(b)
    await session.commit()
    await session.refresh(b)
    c = BookCopyFactory(
        book_id=b.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='RC-SUPER-1',
    )
    session.add(c)
    await session.commit()
    student_token = client.post(
        '/auth/token',
        data={
            'username': student.username,
            'password': student.clean_password,
        },
    ).json()['access_token']
    r = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': b.id},
    )
    assert r.status_code == HTTPStatus.CREATED
    resp = client.get(
        '/reservations/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] >= 1
