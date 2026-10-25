from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from family_pnl.api.deps import get_rate_source, get_session
from family_pnl.core.db import create_session_factory
from family_pnl.integrations.nbrb import NbrbClient, create_http_client


async def test_get_session_yields_a_working_session_and_closes_it(engine: AsyncEngine) -> None:
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=create_session_factory(engine)))
    )
    sessions = get_session(request)

    session = await anext(sessions)
    assert await session.scalar(text("SELECT 1")) == 1
    await sessions.aclose()

    assert not session.in_transaction()


async def test_the_rate_source_is_the_nbrb_client_over_the_apps_http_client() -> None:
    http = create_http_client()
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(nbrb_http=http)))
    try:
        assert isinstance(get_rate_source(request), NbrbClient)
    finally:
        await http.aclose()


class RecordingSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "RecordingSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def request_with(session: RecordingSession) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=lambda: session))
    )


async def test_a_request_that_succeeds_is_committed_at_the_end() -> None:
    session = RecordingSession()
    sessions = get_session(request_with(session))
    await anext(sessions)

    with pytest.raises(StopAsyncIteration):
        await anext(sessions)

    assert session.commits == 1


async def test_a_request_that_fails_is_not_committed() -> None:
    session = RecordingSession()
    sessions = get_session(request_with(session))
    await anext(sessions)

    with pytest.raises(RuntimeError):
        await sessions.athrow(RuntimeError("the endpoint failed"))

    assert session.commits == 0
