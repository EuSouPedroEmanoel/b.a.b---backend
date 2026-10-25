from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus

import pytest
from sqlalchemy import select

from src.models import (
    AdministrativeActivity,
    BooksStates,
    Loan,
    LoanStatus,
    PrivacyProcessingMode,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    SchoolPrivacyPolicy,
    User,
)
from tests.factories import BookCopyFactory


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.asyncio
async def test_privacy_profile_is_limited_to_authenticated_user(client, token):
    response = client.get('/privacy/me', headers=_headers(token))
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert set(body) == {
        'account',
        'library',
        'preferences',
        'security',
        'sharing',
        'correction_guidance',
        'preservation',
        'privacy_contact_email',
    }
    assert 'password' not in body['account']
    assert 'tokens' in body['security']


def test_privacy_central_rejects_guest(client, school):
    guest = client.post('/auth/guest', json={'school_code': school.code})
    response = client.get(
        '/privacy/me', headers=_headers(guest.json()['access_token'])
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_privacy_operator_rejects_reader_role(client, student_token):
    response = client.get(
        '/privacy/requests', headers=_headers(student_token)
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_privacy_request_cancel_boundaries(client, token):
    missing = client.post(
        '/privacy/me/requests/999999/cancel', headers=_headers(token)
    )
    assert missing.status_code == HTTPStatus.NOT_FOUND

    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction'},
    )
    request_id = created.json()['id']
    cancelled = client.post(
        f'/privacy/me/requests/{request_id}/cancel',
        headers=_headers(token),
    )
    assert cancelled.status_code == HTTPStatus.OK
    repeated = client.post(
        f'/privacy/me/requests/{request_id}/cancel',
        headers=_headers(token),
    )
    assert repeated.status_code == HTTPStatus.CONFLICT


def test_librarian_cannot_change_school_privacy_policy(client, token, school):
    response = client.put(
        f'/privacy/schools/{school.id}/policy',
        headers=_headers(token),
        json={
            'processing_mode': 'administrative_review',
            'justification': 'Atualização da política institucional.',
        },
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_privacy_export_requires_current_password(
    client, token, session, user
):
    current = await session.scalar(select(User).where(User.id == user.id))
    assert current is not None
    current.birthdate = date(2010, 1, 2)
    await session.commit()

    invalid = client.post(
        '/privacy/me/export',
        headers=_headers(token),
        json={'password': 'wrong-password'},
    )
    assert invalid.status_code == HTTPStatus.UNAUTHORIZED

    valid = client.post(
        '/privacy/me/export',
        headers=_headers(token),
        json={'password': 'testteste'},
    )
    assert valid.status_code == HTTPStatus.OK
    body = valid.json()
    assert body['export_version'] == '1.0'
    assert body['data']['account']['birthdate'] == '2010-01-02'
    assert 'password' not in str(body)
    forbidden_keys = {
        'password',
        'password_hash',
        'cpf_lookup_hash',
        'cpf_collision_guard',
        'access_token',
        'refresh_token',
        'activation_token',
        'reset_token',
        'secret',
        'hmac',
    }

    def collect_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key.lower()
                yield from collect_keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from collect_keys(item)

    assert not forbidden_keys.intersection(collect_keys(body))


@pytest.mark.asyncio
async def test_privacy_request_lifecycle_and_school_scope(
    client, token, school_admin_token, other_school
):
    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction', 'description': 'Nome'},
    )
    assert created.status_code == HTTPStatus.CREATED
    request_id = created.json()['id']

    mine = client.get('/privacy/me/requests', headers=_headers(token))
    assert mine.status_code == HTTPStatus.OK
    assert mine.json()['items'][0]['id'] == request_id

    policy = client.get(
        f'/privacy/schools/{other_school.id}/policy',
        headers=_headers(school_admin_token),
    )
    assert policy.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_school_admin_cannot_read_or_decide_other_school_request(
    client, session, user, school_admin_token, other_school
):
    foreign = PrivacyRequest(
        user_id=user.id,
        school_id=other_school.id,
        request_type=PrivacyRequestType.CORRECTION,
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)

    listed = client.get(
        '/privacy/requests', headers=_headers(school_admin_token)
    )
    decided = client.post(
        f'/privacy/requests/{foreign.id}/decision',
        headers=_headers(school_admin_token),
        json={'status': 'fulfilled'},
    )
    assert listed.status_code == HTTPStatus.OK
    assert all(item['id'] != foreign.id for item in listed.json()['items'])
    assert decided.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_privacy_requests_require_privacy_operator(client, token):
    response = client.get('/privacy/requests', headers=_headers(token))
    assert response.status_code == HTTPStatus.OK


def test_consent_revocation_is_not_available_without_consent_support(
    client, token
):
    response = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'consent_revocation'},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_privacy_request_terminal_transition_is_rejected(
    client, token, school_admin_token
):
    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction'},
    )
    request_id = created.json()['id']

    fulfilled = client.post(
        f'/privacy/requests/{request_id}/decision',
        headers=_headers(school_admin_token),
        json={'status': 'fulfilled'},
    )
    assert fulfilled.status_code == HTTPStatus.OK

    rejected = client.post(
        f'/privacy/requests/{request_id}/decision',
        headers=_headers(school_admin_token),
        json={'status': 'denied', 'resolution': 'Após conclusão.'},
    )
    assert rejected.status_code == HTTPStatus.CONFLICT


def test_privacy_decision_requires_resolution_for_denial(
    client, token, school_admin_token
):
    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction'},
    )
    response = client.post(
        f"/privacy/requests/{created.json()['id']}/decision",
        headers=_headers(school_admin_token),
        json={'status': 'denied'},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_privacy_request_cancellation_is_audited(
    client, session, token
):
    created = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'correction'},
    )
    request_id = created.json()['id']

    cancelled = client.post(
        f'/privacy/me/requests/{request_id}/cancel',
        headers=_headers(token),
    )
    assert cancelled.status_code == HTTPStatus.OK
    activity = await session.scalar(
        select(AdministrativeActivity).where(
            AdministrativeActivity.entity_type == 'privacy_request',
            AdministrativeActivity.entity_id == str(request_id),
            AdministrativeActivity.operation == 'cancelled',
        )
    )
    assert activity is not None


@pytest.mark.asyncio
async def test_automatic_anonymization_revokes_account(
    client, session, token, user
):
    response = client.post(
        '/privacy/me/requests',
        headers=_headers(token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['status'] == 'fulfilled'

    current = await session.scalar(select(User).where(User.id == user.id))
    assert current is not None
    assert current.name == 'Titular anonimizado'
    assert current.password is None
    assert current.is_active is False


@pytest.mark.asyncio
async def test_tokens_and_login_are_invalid_after_anonymization(
    client, student, student_token
):
    token_pair = client.post(
        '/auth/token',
        data={'username': student.username, 'password': 'testteste'},
    ).json()
    request = client.post(
        '/privacy/me/requests',
        headers=_headers(student_token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert request.status_code == HTTPStatus.CREATED

    protected = client.get(
        '/privacy/me', headers=_headers(token_pair['access_token'])
    )
    refresh = client.post(
        '/auth/refresh', json={'refresh_token': token_pair['refresh_token']}
    )
    login = client.post(
        '/auth/token',
        data={'username': student.username, 'password': 'testteste'},
    )
    assert protected.status_code == HTTPStatus.UNAUTHORIZED
    assert refresh.status_code == HTTPStatus.UNAUTHORIZED
    assert login.status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }


@pytest.mark.asyncio
async def test_privacy_policy_update_and_admin_request_listing(
    client, school_admin_token, school, super_admin_token, other_school
):
    updated = client.put(
        f'/privacy/schools/{school.id}/policy',
        headers=_headers(school_admin_token),
        json={
            'processing_mode': 'administrative_review',
            'justification': 'Atualização da política institucional.',
        },
    )
    assert updated.status_code == HTTPStatus.OK
    assert updated.json()['processing_mode'] == 'administrative_review'
    initial = client.get(
        f'/privacy/schools/{school.id}/policy',
        headers=_headers(school_admin_token),
    )
    assert initial.status_code == HTTPStatus.OK
    listed = client.get(
        '/privacy/requests', headers=_headers(school_admin_token)
    )
    assert listed.status_code == HTTPStatus.OK
    default_policy = client.get(
        f'/privacy/schools/{other_school.id}/policy',
        headers=_headers(super_admin_token),
    )
    assert default_policy.status_code == HTTPStatus.OK
    assert default_policy.json()['processing_mode'] == 'automatic_anonymization'


def test_public_privacy_policy_exposes_only_school_channel(
    client, school, school_admin_token
):
    updated = client.put(
        f'/privacy/schools/{school.id}/policy',
        headers=_headers(school_admin_token),
        json={
            'processing_mode': 'automatic_anonymization',
            'privacy_contact_email': 'privacidade@escola.example',
            'justification': 'Cadastro do canal institucional.',
        },
    )
    assert updated.status_code == HTTPStatus.OK

    response = client.get(f'/privacy/public/{school.code}')
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        'school_id': school.id,
        'school_name': school.name,
        'privacy_contact_email': 'privacidade@escola.example',
        'notice_version': '1.0.0',
    }


@pytest.mark.asyncio
async def test_pending_anonymization_is_reprocessed_after_last_loan_returned(
    client, session, token, student, student_token, user, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.flush()
    loan = Loan(
        copy_id=copy.id,
        user_id=student.id,
        school_id=user.school_id,
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status=LoanStatus.ACTIVE,
        late_days=0,
    )
    session.add(loan)
    await session.commit()

    created = client.post(
        '/privacy/me/requests',
        headers=_headers(student_token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert created.status_code == HTTPStatus.CREATED
    assert created.json()['status'] == 'pending'

    returned = client.post(
        f'/loans/{loan.id}/return', headers=_headers(token)
    )
    assert returned.status_code == HTTPStatus.OK

    session.expire_all()
    current = await session.get(User, student.id)
    request = await session.scalar(
        select(PrivacyRequest).where(PrivacyRequest.user_id == student.id)
    )
    assert current is not None and current.is_active is False
    assert request is not None
    assert request.status == PrivacyRequestStatus.FULFILLED


@pytest.mark.asyncio
async def test_pending_anonymization_respects_administrative_policy(
    client, session, token, student, student_token, user, book
):
    session.add(
        SchoolPrivacyPolicy(
            school_id=user.school_id,
            processing_mode=PrivacyProcessingMode.ADMINISTRATIVE_REVIEW,
        )
    )
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.flush()
    loan = Loan(
        copy_id=copy.id,
        user_id=student.id,
        school_id=user.school_id,
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status=LoanStatus.ACTIVE,
        late_days=0,
    )
    session.add(loan)
    await session.commit()

    created = client.post(
        '/privacy/me/requests',
        headers=_headers(student_token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert created.status_code == HTTPStatus.CREATED
    assert created.json()['status'] == 'pending'

    returned = client.post(
        f'/loans/{loan.id}/return', headers=_headers(token)
    )
    assert returned.status_code == HTTPStatus.OK

    session.expire_all()
    current = await session.get(User, student.id)
    request = await session.scalar(
        select(PrivacyRequest).where(PrivacyRequest.user_id == student.id)
    )
    assert current is not None and current.is_active is True
    assert request is not None
    assert request.status == PrivacyRequestStatus.PENDING


@pytest.mark.asyncio
async def test_reprocessing_is_idempotent_after_account_anonymization(
    client, session, token, student, student_token, user, book
):
    copy = BookCopyFactory(
        book_id=book.id,
        user_id=user.id,
        school_id=user.school_id,
        state=BooksStates.BORROWED,
    )
    session.add(copy)
    await session.flush()
    loan = Loan(
        copy_id=copy.id,
        user_id=student.id,
        school_id=user.school_id,
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status=LoanStatus.ACTIVE,
        late_days=0,
    )
    session.add(loan)
    await session.commit()

    created = client.post(
        '/privacy/me/requests',
        headers=_headers(student_token),
        json={'request_type': 'anonymization', 'password': 'testteste'},
    )
    assert created.status_code == HTTPStatus.CREATED

    returned = client.post(
        f'/loans/{loan.id}/return', headers=_headers(token)
    )
    assert returned.status_code == HTTPStatus.OK
    first_count = await session.scalar(
        select(AdministrativeActivity).where(
            AdministrativeActivity.operation == 'anonymized',
            AdministrativeActivity.entity_id == str(student.id),
        ).with_only_columns(AdministrativeActivity.id)
    )

    from src.services.privacy import reprocess_pending_anonymization

    assert await reprocess_pending_anonymization(session, student.id) == 0
    await session.commit()
    second_count = await session.scalar(
        select(AdministrativeActivity).where(
            AdministrativeActivity.operation == 'anonymized',
            AdministrativeActivity.entity_id == str(student.id),
        ).with_only_columns(AdministrativeActivity.id)
    )
    assert first_count == second_count
