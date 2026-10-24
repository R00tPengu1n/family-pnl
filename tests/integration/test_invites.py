from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.models import Household, Invite
from tests.integration.helpers import Actor, log_in, sign_up


async def create_invite(client: AsyncClient, owner: Actor) -> str:
    response = await client.post("/household/invites", headers=owner.headers)
    assert response.status_code == 201, response.text
    code: str = response.json()["code"]
    return code


async def redeem(client: AsyncClient, actor: Actor, code: str) -> int:
    response = await client.post(f"/household/invites/{code}/redeem", headers=actor.headers)
    return response.status_code


async def join(client: AsyncClient, owner: Actor, email: str) -> Actor:
    """A new user who joined the owner's household as a member."""
    newcomer = await sign_up(client, email)
    assert await redeem(client, newcomer, await create_invite(client, owner)) == 200
    return await log_in(client, email)


async def test_owner_creates_an_invite_valid_for_48_hours(
    client: AsyncClient, clock: FrozenClock
) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.post("/household/invites", headers=anna.headers)

    assert response.status_code == 201
    body = response.json()
    assert len(body["code"]) >= 16
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=48)


async def test_only_the_digest_of_the_code_is_stored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = await create_invite(client, anna)

    stored = (await db_session.scalars(select(Invite))).all()

    assert len(stored) == 1
    assert stored[0].code_hash != code
    assert code not in stored[0].code_hash


async def test_redeeming_moves_the_user_into_the_household_as_a_member(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    anna = await sign_up(client, "anna@example.com", household_name="Ivanovs")
    ivan = await sign_up(client, "ivan@example.com")
    code = await create_invite(client, anna)

    response = await client.post(f"/household/invites/{code}/redeem", headers=ivan.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "member"
    assert body["household"]["id"] == str(anna.household_id)
    assert body["household"]["name"] == "Ivanovs"
    # Ivan's own household was empty and is gone.
    assert await db_session.get(Household, ivan.household_id) is None


async def test_a_code_works_only_once(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    ivan = await sign_up(client, "ivan@example.com")
    olga = await sign_up(client, "olga@example.com")
    code = await create_invite(client, anna)
    assert await redeem(client, ivan, code) == 200

    response = await client.post(f"/household/invites/{code}/redeem", headers=olga.headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invite_invalid"


async def test_a_code_expires_after_48_hours(client: AsyncClient, clock: FrozenClock) -> None:
    anna = await sign_up(client, "anna@example.com")
    ivan = await sign_up(client, "ivan@example.com")
    code = await create_invite(client, anna)

    clock.advance(timedelta(hours=48))
    ivan = await log_in(client, ivan.email)  # the old access token expired long ago

    assert await redeem(client, ivan, code) == 422


async def test_an_unknown_code_is_invalid(client: AsyncClient) -> None:
    ivan = await sign_up(client, "ivan@example.com")

    assert await redeem(client, ivan, "x" * 22) == 422


async def test_redeeming_an_invite_to_your_own_household_is_a_conflict(
    client: AsyncClient,
) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = await create_invite(client, anna)

    response = await client.post(f"/household/invites/{code}/redeem", headers=anna.headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_member"


async def test_a_user_sharing_a_household_cannot_switch_to_another(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    await join(client, anna, "ivan@example.com")
    bob = await sign_up(client, "bob@example.com")

    response = await client.post(
        f"/household/invites/{await create_invite(client, bob)}/redeem", headers=anna.headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "household_not_empty"


async def test_a_member_cannot_create_invites(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    ivan = await join(client, anna, "ivan@example.com")

    response = await client.post("/household/invites", headers=ivan.headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_members_list_is_the_same_for_everyone_in_the_household(
    client: AsyncClient,
) -> None:
    anna = await sign_up(client, "anna@example.com")
    ivan = await join(client, anna, "ivan@example.com")

    for actor in (anna, ivan):
        response = await client.get("/household/members", headers=actor.headers)
        assert response.status_code == 200
        members = response.json()
        assert [(m["email"], m["role"]) for m in members] == [
            ("anna@example.com", "owner"),
            ("ivan@example.com", "member"),
        ]


async def test_members_of_another_household_are_never_listed(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    await join(client, anna, "ivan@example.com")
    bob = await sign_up(client, "bob@example.com")

    response = await client.get("/household/members", headers=bob.headers)

    assert [m["email"] for m in response.json()] == ["bob@example.com"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/household/invites"),
        ("POST", "/household/invites/somecode/redeem"),
        ("GET", "/household/members"),
    ],
)
async def test_household_endpoints_require_authentication(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)

    assert response.status_code == 401
