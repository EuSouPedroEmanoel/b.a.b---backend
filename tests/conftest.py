import os

# Garante que Settings() funciona mesmo sem .env (CI) para chaves não sensíveis
# SUPER_ADMIN fica com defaults em scr/settings.py:14-16
# e mock via fixture mock_super_admin_settings
# DEVE vir antes de importar scr.* que instanciam Settings()
os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://test:test@localhost:5432/test')
os.environ.setdefault('GOOGLE_BOOKS_API_KEY', 'test-key')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-tests-1234567890')
os.environ.setdefault('ALGORITHM', 'HS256')
os.environ.setdefault('ACCESS_TOKEN_EXPIRE_MINUTES', '30')

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import factory
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from scr.app import app
from scr.database import get_session
from scr.models import School, User, UserRole, table_registry
from scr.security import get_password_hash
from scr.settings import Settings
from tests.factories import BookFactory, SchoolFactory


@pytest.fixture
def client(session):
    def get_session_override():
        return session

    with TestClient(app) as client:
        app.dependency_overrides[get_session] = get_session_override
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(scope='session')
def engine():
    with PostgresContainer(
        'postgres:18',
        driver='psycopg',
    ) as postgres:
        yield create_async_engine(postgres.get_connection_url())


@pytest_asyncio.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(table_registry.metadata.create_all)

    async with AsyncSession(engine) as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(table_registry.metadata.drop_all)


@contextmanager
def _mock_db_time(*, model, time=datetime(2026, 6, 25)):
    def fake_time_hook(mapper, connection, target):
        if hasattr(target, 'created_at'):
            target.created_at = time
        if hasattr(target, 'updated_at'):
            target.updated_at = time

    event.listen(model, 'before_insert', fake_time_hook)
    yield time
    event.remove(model, 'before_insert', fake_time_hook)


@pytest.fixture
def mock_db_time():
    return _mock_db_time


@pytest_asyncio.fixture
async def school(session: AsyncSession):
    sch = SchoolFactory()
    session.add(sch)
    await session.commit()
    await session.refresh(sch)
    session.expunge(sch)
    return sch


@pytest_asyncio.fixture
async def other_school(session: AsyncSession):
    sch = SchoolFactory()
    session.add(sch)
    await session.commit()
    await session.refresh(sch)
    session.expunge(sch)
    return sch


@pytest_asyncio.fixture
async def user(session: AsyncSession, school: School):
    password = 'testteste'
    user = UserFactory(
        password=get_password_hash(password),
        role=UserRole.LIBRARIAN,
        school_id=school.id,
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    session.expunge(user)

    user.clean_password = password  # type: ignore[attr-defined]
    return user


@pytest_asyncio.fixture
async def other_user(session: AsyncSession, school: School):
    password = 'testteste'
    user = UserFactory(
        password=get_password_hash(password),
        role=UserRole.LIBRARIAN,
        school_id=school.id,
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    session.expunge(user)

    user.clean_password = password  # type: ignore[attr-defined]
    return user


@pytest_asyncio.fixture
async def school_admin(session: AsyncSession, school: School):
    password = 'testteste'
    user = UserFactory(
        password=get_password_hash(password),
        role=UserRole.SCHOOL_ADMIN,
        school_id=school.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    session.expunge(user)
    user.clean_password = password  # type: ignore[attr-defined]
    return user


@pytest_asyncio.fixture
async def super_admin(session: AsyncSession):
    password = 'testteste'
    user = UserFactory(
        password=get_password_hash(password),
        role=UserRole.SUPER_ADMIN,
        school_id=None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    session.expunge(user)
    user.clean_password = password  # type: ignore[attr-defined]
    return user


@pytest.fixture
def token(client, user):
    response = client.post(
        '/auth/token',
        data={'username': user.username, 'password': user.clean_password},
    )

    return response.json()['access_token']


@pytest.fixture
def school_admin_token(client, school_admin):
    response = client.post(
        '/auth/token',
        data={
            'username': school_admin.username,
            'password': school_admin.clean_password,
        },
    )
    return response.json()['access_token']


@pytest.fixture
def super_admin_token(client, super_admin):
    response = client.post(
        '/auth/token',
        data={
            'username': super_admin.username,
            'password': super_admin.clean_password,
        },
    )
    return response.json()['access_token']


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def mock_super_admin_settings(monkeypatch):
    """Mock das credenciais SUPER_ADMIN para testes isolados."""
    monkeypatch.setenv('SUPER_ADMIN_USERNAME', 'mock_super')
    monkeypatch.setenv('SUPER_ADMIN_EMAIL', 'mock@exemplo.com')
    monkeypatch.setenv('SUPER_ADMIN_PASSWORD', 'mock123')
    # patch no objeto já instanciado em scr.seeds / scr.security se necessário
    with patch('scr.settings.Settings') as MockSettings:
        MockSettings.return_value.SUPER_ADMIN_USERNAME = 'mock_super'
        MockSettings.return_value.SUPER_ADMIN_EMAIL = 'mock@exemplo.com'
        MockSettings.return_value.SUPER_ADMIN_PASSWORD = 'mock123'
        yield MockSettings


@pytest_asyncio.fixture
async def book(session: AsyncSession, user):
    book = BookFactory(user_id=user.id)

    session.add(book)
    await session.commit()
    await session.refresh(book)

    session.expunge(book)

    return book


class UserFactory(factory.Factory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f'test{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@exemple.com')
    password = factory.LazyAttribute(lambda obj: f'{obj.username}@exemple.com')
    role = UserRole.LIBRARIAN
    school_id = None
