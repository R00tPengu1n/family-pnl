import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import structlog
from sqlalchemy.exc import OperationalError

from family_pnl.core.db import ping


class FailingEngine:
    def __init__(self, error: BaseException | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Any]:
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        yield None


def refused() -> OperationalError:
    try:
        raise ConnectionRefusedError("refused")
    except ConnectionRefusedError as cause:
        error = OperationalError("SELECT 1", {}, cause)
        error.__cause__ = cause
        return error


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        (FailingEngine(refused()), "ConnectionRefusedError"),
        (FailingEngine(OSError("network unreachable")), "OSError"),
        (FailingEngine(delay=1.0), "TimeoutError"),
    ],
)
async def test_ping_logs_the_root_cause_and_returns_false(engine: Any, expected: str) -> None:
    with structlog.testing.capture_logs() as logs:
        assert await ping(engine, seconds=0.05) is False

    assert logs == [{"event": "database_unavailable", "error": expected, "log_level": "warning"}]
