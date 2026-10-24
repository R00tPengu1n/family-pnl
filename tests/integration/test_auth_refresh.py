"""Refresh token rotation, reuse detection and logout (ADR-0005)."""

from datetime import timedelta
from typing import Any

import structlog
from httpx import AsyncClient, Response

from family_pnl.core.clock import FrozenClock

PASSWORD = "correct horse battery"


async def signed_up(client: AsyncClient, email: str = "anna@example.com") -> dict[str, Any]:
    registered = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201, registered.text
    return await log_in(client, email)


async def log_in(client: AsyncClient, email: str = "anna@example.com") -> dict[str, Any]:
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    tokens: dict[str, Any] = response.json()
    return tokens


async def refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post("/auth/refresh", json={"refresh_token": refresh_token})


async def test_refresh_returns_a_new_pair_that_works(client: AsyncClient) -> None:
    tokens = await signed_up(client)

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    me = await client.get("/me", headers={"Authorization": f"Bearer {rotated['access_token']}"})
    assert me.status_code == 200
    assert (await refresh(client, rotated["refresh_token"])).status_code == 200


async def test_a_rotated_refresh_token_cannot_be_used_again(client: AsyncClient) -> None:
    tokens = await signed_up(client)
    await refresh(client, tokens["refresh_token"])

    reused = await refresh(client, tokens["refresh_token"])

    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "invalid_refresh_token"


async def test_reuse_revokes_every_token_of_that_login(client: AsyncClient) -> None:
    # An attacker replays the old token after the user has rotated it: both lose the session.
    tokens = await signed_up(client)
    rotated = (await refresh(client, tokens["refresh_token"])).json()

    with structlog.testing.capture_logs() as logs:
        await refresh(client, tokens["refresh_token"])

    assert (await refresh(client, rotated["refresh_token"])).status_code == 401
    # A replay is a security event: it is logged for the operator.
    assert [log["event"] for log in logs] == ["refresh_token_reuse"]


async def test_reuse_does_not_touch_other_logins(client: AsyncClient) -> None:
    phone = await signed_up(client)
    laptop = await log_in(client)
    await refresh(client, phone["refresh_token"])

    await refresh(client, phone["refresh_token"])

    assert (await refresh(client, laptop["refresh_token"])).status_code == 200


async def test_refresh_token_expires_after_30_days(client: AsyncClient, clock: FrozenClock) -> None:
    tokens = await signed_up(client)

    clock.advance(timedelta(days=30))

    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


async def test_unknown_refresh_token_is_rejected(client: AsyncClient) -> None:
    response = await refresh(client, "a" * 43)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_logout_ends_the_login_session(client: AsyncClient) -> None:
    tokens = await signed_up(client)
    rotated = (await refresh(client, tokens["refresh_token"])).json()

    response = await client.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]})

    assert response.status_code == 204
    assert (await refresh(client, rotated["refresh_token"])).status_code == 401


async def test_logout_with_an_unknown_token_is_silent(client: AsyncClient) -> None:
    # Logout never reveals whether a token existed.
    response = await client.post("/auth/logout", json={"refresh_token": "b" * 43})

    assert response.status_code == 204


async def test_logout_leaves_other_logins_signed_in(client: AsyncClient) -> None:
    phone = await signed_up(client)
    laptop = await log_in(client)

    await client.post("/auth/logout", json={"refresh_token": phone["refresh_token"]})

    assert (await refresh(client, laptop["refresh_token"])).status_code == 200
