from http import HTTPStatus

import pytest

from src.models import User, UserRole
from src.security import get_password_hash
from tests.factories import BookCopyFactory, BookFactory


def _auth(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_school_book_customizations_are_isolated_and_restorable(
    session, client, user, token, other_school, super_admin, super_admin_token
):
    other_password = 'other-password'
    other_user = User(
        username='other-school-librarian',
        name='Other librarian',
        email='other-school-librarian@example.com',
        password=get_password_hash(other_password),
        role=UserRole.LIBRARIAN,
        school_id=other_school.id,
    )
    session.add(other_user)
    book = BookFactory(
        user_id=super_admin.id,
        title='Título global',
        description='Descrição global',
    )
    session.add(book)
    await session.commit()
    await session.refresh(book)
    session.add_all([
        BookCopyFactory(
            book_id=book.id,
            added_by=user.id,
            school_id=user.school_id,
        ),
        BookCopyFactory(
            book_id=book.id,
            added_by=other_user.id,
            school_id=other_school.id,
            code='OTHER-SCHOOL-BOOK',
        ),
    ])
    await session.commit()
    other_token = client.post(
        '/auth/token',
        data={'username': other_user.username, 'password': other_password},
    ).json()['access_token']

    update = client.patch(
        f'/books/{book.id}/customization',
        headers=_auth(token),
        json={
            'title': 'Título da Escola A',
            'description': None,
            'author_names': ['Autor da Escola A'],
            'genre_names': ['Gênero da Escola A'],
        },
    )
    assert update.status_code == HTTPStatus.OK
    assert update.json()['title'] == 'Título da Escola A'
    assert update.json()['description'] is None
    assert update.json()['author_names'] == ['Autor da Escola A']

    school_a = client.get(f'/books/{book.id}', headers=_auth(token))
    school_b = client.get(f'/books/{book.id}', headers=_auth(other_token))
    global_book = client.get(
        f'/books/{book.id}', headers=_auth(super_admin_token)
    )
    assert school_a.json()['title'] == 'Título da Escola A'
    assert school_a.json()['description'] is None
    assert school_b.json()['title'] == 'Título global'
    assert school_b.json()['description'] == 'Descrição global'
    assert global_book.json()['title'] == 'Título global'

    state = client.get(
        f'/books/{book.id}/customization', headers=_auth(token)
    )
    assert state.status_code == HTTPStatus.OK
    assert state.json()['overridden_fields'] == [
        'title', 'description', 'genres', 'authors'
    ]

    update_b = client.patch(
        f'/books/{book.id}/customization',
        headers=_auth(other_token),
        json={'title': 'Título da Escola B'},
    )
    assert update_b.status_code == HTTPStatus.OK
    assert client.get(
        f'/books/{book.id}', headers=_auth(token)
    ).json()['title'] == 'Título da Escola A'
    assert client.get(
        f'/books/{book.id}', headers=_auth(other_token)
    ).json()['title'] == 'Título da Escola B'
    assert client.get(
        f'/books/{book.id}', headers=_auth(super_admin_token)
    ).json()['title'] == 'Título global'

    restored = client.delete(
        f'/books/{book.id}/customization', headers=_auth(token)
    )
    assert restored.status_code == HTTPStatus.OK
    assert client.get(
        f'/books/{book.id}', headers=_auth(token)
    ).json()['title'] == 'Título global'
    assert client.get(
        f'/books/{book.id}', headers=_auth(token)
    ).json()['description'] == 'Descrição global'


@pytest.mark.asyncio
async def test_customization_authorization_does_not_accept_client_school_id(
    client, token, student_token, other_school, book
):
    payload = {'title': 'Tentativa', 'school_id': other_school.id}
    response = client.patch(
        f'/books/{book.id}/customization',
        headers=_auth(token),
        json=payload,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    student_response = client.patch(
        f'/books/{book.id}/customization',
        headers=_auth(student_token),
        json={'title': 'Não permitido'},
    )
    assert student_response.status_code == HTTPStatus.FORBIDDEN

    global_response = client.patch(
        f'/books/{book.id}/global',
        headers=_auth(token),
        json={'title': 'Não permitido'},
    )
    assert global_response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_guest_and_student_receive_effective_book_without_override_metadata(
    session, client, user, token, student_token, school
):
    book = BookFactory(user_id=user.id, title='Título público global')
    session.add(book)
    await session.commit()
    await session.refresh(book)
    session.add(
        BookCopyFactory(
            book_id=book.id,
            added_by=user.id,
            school_id=user.school_id,
            code='PUBLIC-OVERRIDE-BOOK',
        )
    )
    await session.commit()
    updated = client.patch(
        f'/books/{book.id}/customization',
        headers=_auth(token),
        json={'title': 'Título público da escola'},
    )
    assert updated.status_code == HTTPStatus.OK

    guest_token = client.post(
        '/auth/guest', json={'school_code': school.code}
    ).json()['access_token']
    guest_response = client.get(
        f'/books/{book.id}', headers=_auth(guest_token)
    )
    student_response = client.get(
        f'/books/{book.id}', headers=_auth(student_token)
    )
    assert guest_response.status_code == HTTPStatus.OK
    assert student_response.status_code == HTTPStatus.OK
    assert guest_response.json()['title'] == 'Título público da escola'
    assert student_response.json()['title'] == 'Título público da escola'
    assert 'overridden_fields' not in guest_response.json()
    assert 'overridden_fields' not in student_response.json()
    assert 'added_by' not in guest_response.json()


@pytest.mark.asyncio
async def test_superadmin_global_endpoint_changes_only_the_base_record(
    session, client, user, token, super_admin, super_admin_token
):
    book = BookFactory(user_id=super_admin.id, title='Base original')
    session.add(book)
    await session.commit()
    await session.refresh(book)
    response = client.patch(
        f'/books/{book.id}/global',
        headers=_auth(super_admin_token),
        json={'title': 'Base atualizada'},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['title'] == 'Base atualizada'
    assert client.get(
        f'/books/{book.id}', headers=_auth(token)
    ).json()['title'] == 'Base atualizada'
