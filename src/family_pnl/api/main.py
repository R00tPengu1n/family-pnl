"""FastAPI application factory.

Run with `uvicorn --factory family_pnl.api.main:create_app`: settings are read when the
server starts, not when the module is imported.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from family_pnl import __version__
from family_pnl.api.errors import ErrorResponse, register_error_handlers
from family_pnl.api.routers import (
    accounts,
    auth,
    bot,
    budgets,
    categories,
    fx,
    health,
    household,
    operations,
    reports,
)
from family_pnl.core.clock import Clock, SystemClock
from family_pnl.core.config import Settings, get_settings
from family_pnl.core.db import create_engine, create_session_factory
from family_pnl.core.logging import configure_logging
from family_pnl.core.redis import create_redis
from family_pnl.integrations.nbrb import create_http_client


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Creating the engine opens no connection; the pool connects on first use.
    engine = create_engine(settings.database_url)
    redis = create_redis(settings.redis_url)
    nbrb_http = create_http_client(settings.nbrb_base_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json_output=settings.log_json)
        yield
        await engine.dispose()
        await redis.aclose()
        await nbrb_http.aclose()

    app = FastAPI(
        title="Family P&L API",
        version=__version__,
        description="Shared family finances: accounts, operations, budgets and reports.",
        lifespan=lifespan,
        responses={"default": {"model": ErrorResponse, "description": "Error"}},
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.redis = redis
    app.state.nbrb_http = nbrb_http
    app.state.session_factory = create_session_factory(engine)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(household.router)
    app.include_router(bot.router)
    app.include_router(fx.router)
    app.include_router(accounts.router)
    app.include_router(categories.router)
    app.include_router(operations.router)
    app.include_router(budgets.router)
    app.include_router(reports.router)
    return app
