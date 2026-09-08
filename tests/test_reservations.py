import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.models import (
    BookCopy,
    BooksStates,
    Reservation,
    ReservationStatus,
    User,
)
from src.routers import reservations as reservations_router
from src.schemas import ReservationCreate
from src.utils.reservation_queue import promote_copy_to_next_reservation
from tests.factories import BookCopyFactory, ReservationFactory


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
async def test_queue_metrics_include_ready_reservations(
    session, client, user, token, student, teacher, book
):
    """A ready reservation keeps its place while a later reader waits."""
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.RESERVED,
        code='RESERVED-QUEUE-1',
    )
    session.add(copy)
    await session.flush()
    ready = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=user.school_id,
        status=ReservationStatus.READY,
        copy_id=copy.id,
    )
    waiting = ReservationFactory(
        book_id=book.id,
        user_id=teacher.id,
        school_id=user.school_id,
        status=ReservationStatus.ACTIVE,
    )
    session.add_all([ready, waiting])
    await session.commit()

    ready_response = client.get(
        '/reservations/?status=ready',
        headers={'Authorization': f'Bearer {token}'},
    )
    active_response = client.get(
        '/reservations/?status=active',
        headers={'Authorization': f'Bearer {token}'},
    )

    ready_item = next(
        item for item in ready_response.json()['items'] if item['id'] == ready.id
    )
    active_item = next(
        item
        for item in active_response.json()['items']
        if item['id'] == waiting.id
    )
    assert ready_item['queue_position'] == 1
    assert active_item['queue_position'] == 2
    assert ready_item['queue_total'] == active_item['queue_total'] == 2
    assert ready_item['reserver_role'] == 'student'
    assert ready_item['reserver_is_active'] is True


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


@pytest.mark.asyncio
async def test_create_reservation_respects_active_limit(
    session, client, user, student, student_token, book
):
    from tests.factories import BookFactory

    books = [book]
    for index in range(3):
        extra = BookFactory(user_id=user.id)
        session.add(extra)
        await session.commit()
        await session.refresh(extra)
        books.append(extra)

    for index, current_book in enumerate(books):
        copy = BookCopyFactory(
            book_id=current_book.id,
            user_id=user.id,
            school_id=user.school_id,
            state=BooksStates.BORROWED,
            code=f'LIMIT-RES-{index}',
        )
        session.add(copy)
    await session.commit()

    for current_book in books[:3]:
        response = client.post(
            '/reservations/',
            headers={'Authorization': f'Bearer {student_token}'},
            json={'book_id': current_book.id},
        )
        assert response.status_code == HTTPStatus.CREATED

    limited = client.post(
        '/reservations/',
        headers={'Authorization': f'Bearer {student_token}'},
        json={'book_id': books[3].id},
    )
    assert limited.status_code == HTTPStatus.CONFLICT
    assert 'Limite de reservas' in limited.json()['detail']


@pytest.mark.asyncio
async def test_get_reservation_access_and_queue(
    session, client, user, student, teacher, student_token, book, other_school
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code='GET-RESERVATION',
    )
    session.add(copy)
    await session.flush()
    first = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=user.school_id,
        status=ReservationStatus.ACTIVE,
    )
    second = ReservationFactory(
        book_id=book.id,
        user_id=teacher.id,
        school_id=user.school_id,
        status=ReservationStatus.READY,
        copy_id=copy.id,
    )
    foreign = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=other_school.id,
        status=ReservationStatus.ACTIVE,
    )
    session.add_all([first, second, foreign])
    await session.commit()
    await session.refresh(first)
    await session.refresh(foreign)

    own = client.get(
        f'/reservations/{first.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert own.status_code == HTTPStatus.OK
    assert own.json()['queue_position'] == 1
    assert own.json()['queue_total'] == 2

    other_reader = client.get(
        f'/reservations/{second.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert other_reader.status_code == HTTPStatus.FORBIDDEN

    foreign_response = client.get(
        f'/reservations/{foreign.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert foreign_response.status_code == HTTPStatus.NOT_FOUND


def test_active_reservation_integrity_helper():
    matching = IntegrityError('insert', {}, Exception())
    matching.orig.diag = type(
        'Diag', (), {'constraint_name': 'uq_reservations_active_user_book_school'}
    )()
    assert reservations_router._is_active_reservation_conflict(matching)

    other = IntegrityError('insert', {}, Exception())
    other.orig.diag = type('Diag', (), {'constraint_name': 'other_constraint'})()
    assert not reservations_router._is_active_reservation_conflict(other)


@pytest.mark.asyncio
@pytest.mark.parametrize('constraint_name, expected_status', [
    ('uq_reservations_active_user_book_school', HTTPStatus.CONFLICT),
    ('other_constraint', None),
])
async def test_reservation_integrity_error_handling(
    session,
    client,
    student,
    student_token,
    user,
    book,
    monkeypatch,
    constraint_name,
    expected_status,
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
        code=f'INTEGRITY-{constraint_name}',
    )
    session.add(copy)
    await session.commit()

    error = IntegrityError('insert', {}, Exception())
    error.orig.diag = type(
        'Diag', (), {'constraint_name': constraint_name}
    )()

    async def fail_commit():
        raise error

    monkeypatch.setattr(session, 'commit', fail_commit)

    def request():
        return client.post(
            '/reservations/',
            headers={'Authorization': f'Bearer {student_token}'},
            json={'book_id': book.id},
        )
    if expected_status is None:
        with pytest.raises(IntegrityError):
            request()
    else:
        response = request()
        assert response.status_code == expected_status
        assert response.json()['detail'] == 'Active reservation already exists'


@pytest.mark.asyncio
async def test_get_reservation_not_found(client, student_token):
    response = client.get(
        '/reservations/99999',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_ready_reservation_releases_copy(
    session, client, student, student_token, user, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.RESERVED,
        code='CANCEL-READY',
    )
    session.add(copy)
    await session.flush()
    reservation = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=user.school_id,
        status=ReservationStatus.READY,
        copy_id=copy.id,
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)
    copy_id = copy.id

    response = client.delete(
        f'/reservations/{reservation.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert response.status_code == HTTPStatus.OK
    session.expire_all()
    assert (await session.get(BookCopy, copy_id)).state == BooksStates.AVAILABLE


@pytest.mark.asyncio
async def test_cancel_reservation_disappears_after_initial_lookup(
    session, student, user, book, monkeypatch
):
    reservation = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=user.school_id,
        status=ReservationStatus.ACTIVE,
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)

    monkeypatch.setattr(
        reservations_router,
        'lock_book_queue',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        session,
        'scalar',
        AsyncMock(side_effect=[reservation, None]),
    )
    with pytest.raises(HTTPException) as error:
        await reservations_router.cancel_reservation(
            reservation.id, session, student
        )
    assert error.value.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_queue_expires_ineligible_reader(
    session, student, user, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    student.is_active = False
    session.add(student)
    reservation = ReservationFactory(
        book_id=book.id,
        user_id=student.id,
        school_id=user.school_id,
        status=ReservationStatus.ACTIVE,
    )
    session.add_all([copy, reservation])
    await session.commit()
    await session.refresh(copy)

    promoted = await promote_copy_to_next_reservation(session, copy)
    assert promoted is None
    assert reservation.status == ReservationStatus.EXPIRED
    assert copy.state == BooksStates.AVAILABLE


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


@pytest.mark.parametrize('concurrency', [2, 5, 10])
@pytest.mark.asyncio
async def test_concurrent_reservations_same_reader_are_serialized(
    session, engine, user, student, book, concurrency
):
    """Concurrent transactions cannot create the same active reservation.

    The barrier makes every round genuinely simultaneous at the application
    lock boundary while each request uses an independent database session.
    """
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.commit()

    # Synchronize immediately before the database lock so both request scopes
    # genuinely overlap instead of merely running sequentially by accident.
    # Disable psycopg server-side prepared statements for these long-lived
    # independent sessions; the fixture recreates tables between tests.
    isolated_engine = create_async_engine(
        engine.url,
        connect_args={'prepare_threshold': None},
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        isolated_engine, class_=AsyncSession, expire_on_commit=False
    )
    start_barrier = asyncio.Barrier(concurrency)
    try:
        async def submit():
            async with session_factory() as tx:
                reader = await tx.get(User, student.id)
                await start_barrier.wait()
                outcome = None
                try:
                    result = await reservations_router.create_reservation(
                        ReservationCreate(book_id=book.id), tx, reader
                    )
                    outcome = ('created', result['id'])
                except HTTPException as exc:
                    outcome = ('error', exc.status_code)
                finally:
                    if tx.in_transaction():
                        await tx.rollback()
                return outcome

        tasks = [asyncio.create_task(submit()) for _ in range(concurrency)]
        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=30
            )
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    finally:
        await isolated_engine.dispose()

    assert sum(outcome[0] == 'created' for outcome in outcomes) == 1
    assert sum(outcome[0] == 'error' for outcome in outcomes) == concurrency - 1
    assert all(
        outcome[1] == HTTPStatus.CONFLICT
        for outcome in outcomes
        if outcome[0] == 'error'
    )

    persisted = await session.scalar(
        select(func.count(Reservation.id)).where(
            Reservation.book_id == book.id,
            Reservation.user_id == student.id,
            Reservation.school_id == student.school_id,
            Reservation.status.in_([
                ReservationStatus.ACTIVE,
                ReservationStatus.READY,
            ]),
        )
    )
    assert persisted == 1


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
    data = resp.json()
    assert data['total'] == 3
    assert data['page'] == 1
    assert data['size'] == 2
    assert data['pages'] == 2
    assert len(data['items']) == 2


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
    student_items = resp.json()['items']
    assert resp.json()['total'] == 1
    assert [item['id'] for item in student_items] == [r1.json()['id']]
    assert all(item['user_id'] == student.id for item in student_items)
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
    assert resp_lib.json()['total'] == 2
    # filter by status
    resp_status = client.get(
        '/reservations/?status=active',
        headers={'Authorization': f'Bearer {lib_token}'},
    )
    assert resp_status.status_code == HTTPStatus.OK
    assert resp_status.json()['total'] == 2
    assert {item['id'] for item in resp_status.json()['items']} == {
        r1.json()['id'], r2.json()['id']
    }
    # filter by book_id
    resp_book = client.get(
        f'/reservations/?book_id={books[0].id}',
        headers={'Authorization': f'Bearer {lib_token}'},
    )
    assert resp_book.status_code == HTTPStatus.OK
    assert resp_book.json()['total'] == 1
    assert [item['id'] for item in resp_book.json()['items']] == [
        r1.json()['id']
    ]


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
    assert resp.json()['total'] == 1
    assert [item['id'] for item in resp.json()['items']] == [r.json()['id']]
    assert all(x['status'] == 'active' for x in resp.json()['items'])
    # filter by book_id
    resp2 = client.get(
        f'/reservations/me?book_id={b1.id}',
        headers={'Authorization': f'Bearer {student_token}'},
    )
    assert resp2.status_code == HTTPStatus.OK
    assert resp2.json()['total'] == 1
    assert [item['id'] for item in resp2.json()['items']] == [r.json()['id']]
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
    cancel = client.delete(
        f'/reservations/{r.json()["id"]}',
        headers={'Authorization': f'Bearer {super_admin_token}'},
    )
    assert cancel.status_code == HTTPStatus.FORBIDDEN
