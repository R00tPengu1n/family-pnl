"""Worker contexts whose sessions live inside the test transaction."""

import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.worker.context import WorkerContext, build_context

# 21:30 UTC on 19 October is 00:30 on 20 October in Minsk.
WORKER_NOW = datetime(2026, 10, 19, 21, 30, tzinfo=UTC)


@pytest.fixture
def worker_clock() -> FrozenClock:
    return FrozenClock(WORKER_NOW)


@pytest.fixture
async def context(
    settings: Settings, db_session: AsyncSession, worker_clock: FrozenClock
) -> AsyncIterator[WorkerContext]:
    built = build_context(settings, worker_clock)
    factory = async_sessionmaker(
        bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield dataclasses.replace(built, session_factory=factory)
    await built.close()
