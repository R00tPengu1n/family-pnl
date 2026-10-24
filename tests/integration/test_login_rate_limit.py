"""Failed logins are limited per email and per IP (5 per 15 minutes)."""

from collections.abc import Callable

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from redis.asyncio import Redis

from family_pnl.core.config import Settings
from family_pnl.core.redis import create_redis
from family_pnl.services.rate_limit import LoginRateLimiter

PASSWORD = "correct horse battery"
WRONG = "wrong password!!"


async def register(client: AsyncClient, email: str) -> None:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text


async def login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def from_ip(app: FastAPI) -> Callable[[str], AsyncClient]:
    """A client whose requests come from the given IP address."""

    def make(ip: str) -> AsyncClient:
        transport = ASGITransport(app=app, client=(ip, 50000))
        return AsyncClient(transport=transport, base_url="http://test")

    return make


async def test_sixth_attempt_for_an_email_is_refused_even_with_the_right_password(
    client: AsyncClient,
) -> None:
    await register(client, "anna@example.com")
    for _ in range(5):
        assert (await login(client, "anna@example.com", WRONG)).status_code == 401

    response = await login(client, "anna@example.com", PASSWORD)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert 0 < int(response.headers["retry-after"]) <= 15 * 60


async def test_email_limit_applies_across_ip_addresses(
    client: AsyncClient, from_ip: Callable[[str], AsyncClient]
) -> None:
    await register(client, "anna@example.com")
    for i in range(5):
        async with from_ip(f"203.0.113.{i}") as other:
            await login(other, "anna@example.com", WRONG)

    async with from_ip("203.0.113.99") as fresh_ip:
        response = await login(fresh_ip, "anna@example.com", PASSWORD)

    assert response.status_code == 429


async def test_ip_limit_applies_across_emails(client: AsyncClient) -> None:
    await register(client, "anna@example.com")
    for i in range(5):
        await login(client, f"guess{i}@example.com", WRONG)

    response = await login(client, "anna@example.com", PASSWORD)

    assert response.status_code == 429


async def test_other_ips_and_emails_are_not_affected(
    client: AsyncClient, from_ip: Callable[[str], AsyncClient]
) -> None:
    await register(client, "anna@example.com")
    await register(client, "ivan@example.com")
    for _ in range(5):
        await login(client, "anna@example.com", WRONG)

    async with from_ip("198.51.100.7") as other_ip:
        response = await login(other_ip, "ivan@example.com", PASSWORD)

    assert response.status_code == 200


async def test_success_resets_the_email_counter_but_not_the_ip_counter(
    client: AsyncClient, from_ip: Callable[[str], AsyncClient]
) -> None:
    await register(client, "anna@example.com")
    for _ in range(4):
        await login(client, "anna@example.com", WRONG)
    assert (await login(client, "anna@example.com", PASSWORD)).status_code == 200

    # The email starts over (one failure), but this IP is at five failures now.
    await login(client, "anna@example.com", WRONG)
    async with from_ip("198.51.100.8") as other_ip:
        email_still_allowed = await login(other_ip, "anna@example.com", PASSWORD)
    ip_blocked = await login(client, "ivan@example.com", PASSWORD)

    assert email_still_allowed.status_code == 200
    assert ip_blocked.status_code == 429


async def test_counters_expire_with_the_window(client: AsyncClient, redis: Redis) -> None:
    await register(client, "anna@example.com")
    await login(client, "anna@example.com", WRONG)

    keys = await redis.keys("login:fail:*")
    ttls = [await redis.ttl(key) for key in keys]

    assert len(keys) == 2  # one per email, one per IP
    assert all(0 < ttl <= 15 * 60 for ttl in ttls)


async def test_emails_are_not_stored_in_plain_text(client: AsyncClient, redis: Redis) -> None:
    await login(client, "anna@example.com", WRONG)

    keys = await redis.keys("*")

    assert keys
    assert not any("anna" in key for key in keys)


async def test_limiter_fails_open_when_redis_is_down(settings: Settings) -> None:
    # An outage must not lock every user out (ADR-0006); it is logged instead.
    dead = create_redis(SecretStr("redis://127.0.0.1:1/0"))
    limiter = LoginRateLimiter(dead, settings)
    try:
        with structlog.testing.capture_logs() as logs:
            await limiter.check("anna@example.com", "192.0.2.1")
            await limiter.record_failure("anna@example.com", "192.0.2.1")
            await limiter.reset_email("anna@example.com")
    finally:
        await dead.aclose()

    assert [log["event"] for log in logs] == ["rate_limit_unavailable"] * 3
