"""Integration fixtures: real PostgreSQL and Redis (ADR-0003).

PostgreSQL comes from TEST_DATABASE_URL and Redis from TEST_REDIS_URL when set (CI);
otherwise from throwaway testcontainers. Migrations run once per session; every test runs
inside a database transaction that is rolled back and Redis is flushed after it, so tests
never see each other's data.
"""

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from family_pnl.api.deps import get_session
from family_pnl.api.main import create_app
from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Environment, Settings
from family_pnl.core.db import create_engine
from family_pnl.core.redis import create_redis

ALEMBIC_INI = str(Path(__file__).resolve().parents[2] / "alembic.ini")


def alembic_config(database_url: str) -> Config:
    config = Config(ALEMBIC_INI)
    # ConfigParser treats % as interpolation; URL-encoded passwords contain it.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        yield url
        return
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        yield f"redis://{host}:{container.get_exposed_port(6379)}/0"


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = create_redis(SecretStr(redis_url))
    yield client
    # Rate-limit counters must not leak into the next test.
    await client.flushdb()
    await client.aclose()


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture(scope="session")
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(SecretStr(migrated_database_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        # Code under test may commit: commits become savepoints inside the outer transaction.
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def settings(migrated_database_url: str, redis_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        log_json=True,
        database_url=SecretStr(migrated_database_url),
        jwt_secret=SecretStr("integration-tests-jwt-secret-32-chars-min"),
        redis_url=SecretStr(redis_url),
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 24, 9, 0, tzinfo=UTC))


@pytest.fixture
async def app(
    settings: Settings, db_session: AsyncSession, clock: FrozenClock, redis: Redis
) -> AsyncIterator[FastAPI]:
    app = create_app(settings, clock=clock)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = test_session
    yield app
    # ASGITransport does not run the lifespan, so the app's clients are closed here.
    await app.state.engine.dispose()
    await app.state.redis.aclose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
