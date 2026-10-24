import logging
from collections.abc import AsyncIterator, Iterator

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from family_pnl.api.main import create_app
from family_pnl.core.config import Environment, Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        log_json=True,
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost:1/unused"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """configure_logging changes process-wide state; give every test a clean slate."""
    managed = [
        logging.getLogger(),
        *(logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")),
    ]
    saved = [(lg, lg.handlers[:], lg.level, lg.propagate) for lg in managed]
    yield
    structlog.reset_defaults()
    for lg, handlers, level, propagate in saved:
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate
