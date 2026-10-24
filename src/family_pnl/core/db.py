"""Async SQLAlchemy engine and session factory."""

import asyncio

import structlog
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

logger = structlog.get_logger(__name__)


def create_engine(database_url: SecretStr) -> AsyncEngine:
    # pool_pre_ping drops connections that died while idle (database restart, network).
    return _create_async_engine(database_url.get_secret_value(), pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine, seconds: float = 2.0) -> bool:
    """Return True if the database answers `SELECT 1` within `seconds`."""
    try:
        async with asyncio.timeout(seconds), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        # The root cause (refused, bad password) is what an operator needs. A timeout's
        # __cause__ is the internal CancelledError, so it is reported as itself.
        cause = exc if isinstance(exc, TimeoutError) else exc.__cause__ or exc
        logger.warning("database_unavailable", error=type(cause).__name__)
        return False
    return True
