from types import SimpleNamespace
from typing import Any

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
