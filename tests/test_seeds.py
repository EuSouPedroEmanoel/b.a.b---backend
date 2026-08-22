from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scr.models import UserRole  # noqa: F401
from scr.seeds import seed_super_admin


@pytest.mark.asyncio
async def test_seed_super_admin_already_exists(monkeypatch):
    mock_user = MagicMock()
    mock_user.username = 'superadmin'

    mock_session = AsyncMock()
    mock_session.scalar.return_value = mock_user

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    # patch create_async_engine and AsyncSession
    with patch(
        'scr.seeds.create_async_engine', return_value=mock_engine
    ), patch('scr.seeds.AsyncSession') as mock_session_cls:
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session_cls.return_value.__aexit__.return_value = False

        result = await seed_super_admin()
        assert result.username == 'superadmin'
        mock_session.scalar.assert_awaited()
        mock_engine.dispose.assert_awaited()


@pytest.mark.asyncio
async def test_seed_super_admin_creates_new(monkeypatch):
    mock_session = AsyncMock()
    # first call returns None (not exists), second not needed
    mock_session.scalar.return_value = None
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    fake_settings = MagicMock()
    fake_settings.DATABASE_URL = 'sqlite://'
    fake_settings.SUPER_ADMIN_USERNAME = 'newadmin'
    fake_settings.SUPER_ADMIN_EMAIL = 'new@ex.com'
    fake_settings.SUPER_ADMIN_PASSWORD = 'pass123'

    with patch(
        'scr.seeds.create_async_engine', return_value=mock_engine
    ), patch('scr.seeds.AsyncSession') as mock_session_cls, patch(
        'scr.seeds.settings', fake_settings
    ), patch(
        'scr.seeds.get_password_hash', return_value='hashed'
    ):
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session_cls.return_value.__aexit__.return_value = False

        result = await seed_super_admin()
        # should have added user
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited()
        mock_session.refresh.assert_awaited()
        assert result is not None
