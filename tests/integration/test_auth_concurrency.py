"""Concurrent refreshes of one token, on two real connections with real commits.

The per-test rollback fixture shares one connection, so it cannot show row locking; these
tests commit for real and delete their user afterwards (refresh tokens cascade).
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.core.db import create_session_factory
from family_pnl.core.security import hash_refresh_token
from family_pnl.models import Household, User
from family_pnl.repositories.identity import RefreshTokenRepository
from family_pnl.services.auth import AuthService, CurrentUser
from family_pnl.services.rate_limit import LoginRateLimiter

PASSWORD = "correct horse battery"
IP = "192.0.2.10"


@pytest.fixture
async def committed_user(
    engine: AsyncEngine, clock: FrozenClock, settings: Settings, login_limiter: LoginRateLimiter
) -> AsyncIterator[CurrentUser]:
    sessions = create_session_factory(engine)
    async with sessions() as session:
        user = await AuthService(session, clock, settings, login_limiter).register(
            "concurrent@example.com", PASSWORD, "Family"
        )
    yield user
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.execute(delete(Household).where(Household.id == user.household_id))
        await session.commit()


async def test_a_refresh_in_progress_blocks_a_second_refresh_of_the_same_token(
    engine: AsyncEngine,
    clock: FrozenClock,
    settings: Settings,
    login_limiter: LoginRateLimiter,
    committed_user: CurrentUser,
) -> None:
    sessions = create_session_factory(engine)
    async with sessions() as session:
        tokens = await AuthService(session, clock, settings, login_limiter).login(
            committed_user.email, PASSWORD, ip=IP
        )
    token_hash = hash_refresh_token(tokens.refresh_token)

    async with sessions() as first, sessions() as second:
        locked = await RefreshTokenRepository(first).get_for_update(token_hash)
        assert locked is not None
        waiting = asyncio.create_task(RefreshTokenRepository(second).get_for_update(token_hash))

        # Without the row lock the second read would return at once.
        await asyncio.sleep(0.5)
        assert not waiting.done()

        locked.revoked_at = clock.now()
        await first.commit()
        seen_by_second = await asyncio.wait_for(waiting, timeout=5)

    # The second refresh sees the rotation and is handled as a replay, not a second winner.
    assert seen_by_second is not None
    assert seen_by_second.revoked_at is not None
