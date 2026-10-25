"""Integration fixtures: real PostgreSQL and Redis (ADR-0003).

PostgreSQL comes from TEST_DATABASE_URL and Redis from TEST_REDIS_URL when set (CI);
otherwise from throwaway testcontainers. Migrations run once per session; every test runs
inside a database transaction that is rolled back and Redis is flushed after it, so tests
never see each other's data.

With pytest-xdist every worker gets its own database (`<name>_gwN`, created on demand) and
its own Redis database number, so parallel workers never share state.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from family_pnl.api.deps import get_session
from family_pnl.api.main import create_app
from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Environment, Settings
from family_pnl.core.db import create_engine
from family_pnl.core.redis import create_redis
from family_pnl.services.rate_limit import LoginRateLimiter

BOT_SECRET = "integration-tests-bot-secret-of-32-chars"
ALEMBIC_INI = str(Path(__file__).resolve().parents[2] / "alembic.ini")


def alembic_config(database_url: str) -> Config:
    config = Config(ALEMBIC_INI)
    # ConfigParser treats % as interpolation; URL-encoded passwords contain it.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    return config


def _worker_number(worker_id: str) -> int:
    return 0 if worker_id == "master" else int(worker_id.removeprefix("gw"))


def _test_setting(name: str) -> str | None:
    """An environment variable, else the same key in the repository's .env (local runs)."""
    if name in os.environ:
        return os.environ[name]
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return None


def _worker_database(url: str, worker_id: str) -> str:
    """The URL of this worker's own database on a shared server, created if missing."""
    base = make_url(url)
    name = base.database if worker_id == "master" else f"{base.database}_{worker_id}"

    async def create() -> None:
        # The maintenance database always exists; the test database may not yet.
        admin = base.set(drivername="postgresql", database="postgres")
        dsn = admin.render_as_string(hide_password=False)
        connection = await asyncpg.connect(dsn)
        try:
            exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
            if not exists:
                await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    asyncio.run(create())
    return base.set(database=name).render_as_string(hide_password=False)


def _worker_redis(url: str, worker_id: str) -> str:
    """The same Redis server, a database number per worker (Redis has 16 by default)."""
    parts = urlsplit(url)
    base = int(parts.path.lstrip("/") or 0)
    return urlunsplit(parts._replace(path=f"/{(base + _worker_number(worker_id)) % 16}"))


@pytest.fixture(scope="session")
def database_url(worker_id: str) -> Iterator[str]:
    url = _test_setting("TEST_DATABASE_URL")
    if url:
        yield _worker_database(url, worker_id)
        return
    # Imported here: with servers configured (CI, local .env) testcontainers is not needed.
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def redis_url(worker_id: str) -> Iterator[str]:
    url = _test_setting("TEST_REDIS_URL")
    if url:
        yield _worker_redis(url, worker_id)
        return
    from testcontainers.community.redis import RedisContainer

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
        bot_api_secret=SecretStr(BOT_SECRET),
    )


@pytest.fixture
def login_limiter(redis: Redis, settings: Settings) -> LoginRateLimiter:
    return LoginRateLimiter(redis, settings)


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
    await app.state.nbrb_http.aclose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
