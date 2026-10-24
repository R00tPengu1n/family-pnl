"""FastAPI application factory. Run with `uvicorn family_pnl.api.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from family_pnl import __version__
from family_pnl.api.errors import ErrorResponse, register_error_handlers
from family_pnl.api.routers import health
from family_pnl.core.config import Settings, get_settings
from family_pnl.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json_output=settings.log_json)
        yield

    app = FastAPI(
        title="Family P&L API",
        version=__version__,
        description="Shared family finances: accounts, operations, budgets and reports.",
        lifespan=lifespan,
        responses={"default": {"model": ErrorResponse, "description": "Error"}},
    )
    register_error_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
