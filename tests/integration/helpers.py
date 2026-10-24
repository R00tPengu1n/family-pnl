"""Shared helpers for HTTP tests: users with tokens in their own households."""

import uuid
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient

PASSWORD = "correct horse battery"


@dataclass(frozen=True, slots=True)
class Actor:
    email: str
    user_id: uuid.UUID
    household_id: uuid.UUID
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


async def sign_up(client: AsyncClient, email: str, household_name: str = "Family") -> Actor:
    """Register a user (the owner of a new household) and log them in."""
    registered = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "household_name": household_name},
    )
    assert registered.status_code == 201, registered.text
    return await log_in(client, email)


async def log_in(client: AsyncClient, email: str) -> Actor:
    """Log in and read the current household from /me."""
    tokens = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert tokens.status_code == 200, tokens.text
    token = tokens.json()["access_token"]
    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    return Actor(
        email=email,
        user_id=uuid.UUID(body["id"]),
        household_id=uuid.UUID(body["household"]["id"]),
        access_token=token,
    )


async def join_household(client: AsyncClient, owner: Actor, email: str) -> Actor:
    """A new user who joined the owner's household as a member through an invite."""
    newcomer = await sign_up(client, email)
    code = (await client.post("/household/invites", headers=owner.headers)).json()["code"]
    redeemed = await client.post(f"/household/invites/{code}/redeem", headers=newcomer.headers)
    assert redeemed.status_code == 200, redeemed.text
    return await log_in(client, email)


async def assert_hidden_from(
    client: AsyncClient, outsider: Actor, method: str, path: str, json: Any = None
) -> None:
    """Isolation (ADR-0004): an outsider gets the same 404 as for an id that does not exist."""
    foreign = await client.request(method, path, headers=outsider.headers, json=json)
    missing_path = path.rsplit("/", 1)[0] + f"/{uuid.uuid4()}"
    missing = await client.request(method, missing_path, headers=outsider.headers, json=json)

    assert foreign.status_code == 404, f"{method} {path} leaked: {foreign.status_code}"
    assert foreign.json() == missing.json()
