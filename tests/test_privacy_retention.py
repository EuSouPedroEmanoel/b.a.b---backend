from datetime import datetime

import pytest
from sqlalchemy import select

from src.models import AccountStatus, User
from src.services.privacy_retention import run_privacy_retention


@pytest.mark.asyncio
async def test_privacy_retention_anonymizes_old_disabled_accounts_once(
    session, user
):
    target = await session.scalar(select(User).where(User.id == user.id))
    target.is_active = False
    target.account_status = AccountStatus.DISABLED
    target.deactivated_at = datetime(2025, 1, 1)
    await session.commit()

    first = await run_privacy_retention(session, datetime(2026, 1, 2))
    assert first['accounts_anonymized'] == 1

    anonymized = await session.scalar(select(User).where(User.id == user.id))
    assert anonymized.username == f'anonymized-{user.id}'
    assert anonymized.password is None
    assert anonymized.is_active is False

    second = await run_privacy_retention(session, datetime(2026, 1, 2))
    assert second['accounts_anonymized'] == 0
