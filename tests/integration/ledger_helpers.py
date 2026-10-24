"""Helpers to build ledgers through the HTTP API in tests."""

from typing import Any

from httpx import AsyncClient

from tests.integration.helpers import Actor


async def new_account(
    client: AsyncClient, actor: Actor, currency: str, name: str | None = None, **extra: Any
) -> str:
    response = await client.post(
        "/accounts",
        headers=actor.headers,
        json={"name": name or f"{currency} card", "type": "card", "currency": currency, **extra},
    )
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def category_id(client: AsyncClient, actor: Actor, name: str) -> str:
    found = (await client.get("/categories", headers=actor.headers)).json()
    return str(next(c["id"] for c in found if c["name"] == name))


async def record(client: AsyncClient, actor: Actor, **fields: Any) -> dict[str, Any]:
    """POST /operations; dates default to 2026-10-20, which the fake rate source knows."""
    response = await client.post(
        "/operations", headers=actor.headers, json={"operation_date": "2026-10-20", **fields}
    )
    assert response.status_code == 201, response.text
    operation: dict[str, Any] = response.json()
    return operation
