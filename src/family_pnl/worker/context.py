"""What every job needs, built once when the worker starts."""

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from family_pnl.core.clock import Clock, SystemClock
from family_pnl.core.config import Settings, get_settings
from family_pnl.core.db import create_engine, create_session_factory
from family_pnl.core.logging import configure_logging
from family_pnl.integrations import nbrb, telegram

CONTEXT_KEY = "family_pnl"


@dataclass(frozen=True, slots=True)
class WorkerContext:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    nbrb_http: httpx.AsyncClient
    telegram_http: httpx.AsyncClient

    async def close(self) -> None:
        await self.engine.dispose()
        await self.nbrb_http.aclose()
        await self.telegram_http.aclose()


def build_context(settings: Settings | None = None, clock: Clock | None = None) -> WorkerContext:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    return WorkerContext(
        settings=settings,
        clock=clock or SystemClock(),
        engine=engine,
        session_factory=create_session_factory(engine),
        nbrb_http=nbrb.create_http_client(settings.nbrb_base_url),
        telegram_http=telegram.create_http_client(settings.telegram_api_url),
    )


async def startup(ctx: dict[str, Any]) -> None:
    context = build_context()
    configure_logging(context.settings.log_level, json_output=context.settings.log_json)
    ctx[CONTEXT_KEY] = context


async def shutdown(ctx: dict[str, Any]) -> None:
    context: WorkerContext = ctx[CONTEXT_KEY]
    await context.close()


def context_of(ctx: dict[str, Any]) -> WorkerContext:
    found: WorkerContext = ctx[CONTEXT_KEY]
    return found
