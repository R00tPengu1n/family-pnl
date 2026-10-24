from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.helpers import Actor, assert_hidden_from, join_household, sign_up


async def create_account(client: AsyncClient, actor: Actor, **fields: Any) -> dict[str, Any]:
    body = {"name": "Card", "type": "card", "currency": "BYN", **fields}
    response = await client.post("/accounts", headers=actor.headers, json=body)
    assert response.status_code == 201, response.text
    account: dict[str, Any] = response.json()
    return account


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


@pytest.fixture
async def ivan(client: AsyncClient, anna: Actor) -> Actor:
    return await join_household(client, anna, "ivan@example.com")


@pytest.fixture
async def bob(client: AsyncClient) -> Actor:
    return await sign_up(client, "bob@example.com")


async def test_a_member_creates_a_personal_account(client: AsyncClient, ivan: Actor) -> None:
    account = await create_account(client, ivan, name="Ivan card", currency="RUB")

    assert account["name"] == "Ivan card"
    assert account["type"] == "card"
    assert account["currency"] == "RUB"
    assert account["shared"] is False
    assert account["holder_id"] == str(ivan.user_id)
    assert account["archived"] is False


async def test_the_owner_creates_a_shared_account(client: AsyncClient, anna: Actor) -> None:
    account = await create_account(client, anna, name="Family cash", type="cash", shared=True)

    assert account["shared"] is True
    assert account["holder_id"] is None


async def test_a_member_cannot_create_a_shared_account(client: AsyncClient, ivan: Actor) -> None:
    response = await client.post(
        "/accounts",
        headers=ivan.headers,
        json={"name": "Pot", "type": "cash", "currency": "BYN", "shared": True},
    )

    assert response.status_code == 403


async def test_everyone_in_the_household_sees_all_its_accounts(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    await create_account(client, anna, name="Anna card")
    await create_account(client, ivan, name="Ivan card")
    await create_account(client, anna, name="Family cash", shared=True)

    for actor in (anna, ivan):
        names = [a["name"] for a in (await client.get("/accounts", headers=actor.headers)).json()]
        assert names == ["Anna card", "Family cash", "Ivan card"]


async def test_a_member_cannot_change_another_members_account(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    annas = await create_account(client, anna, name="Anna card")

    response = await client.patch(
        f"/accounts/{annas['id']}", headers=ivan.headers, json={"name": "Mine now"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_a_member_cannot_change_a_shared_account(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    shared = await create_account(client, anna, shared=True)

    response = await client.patch(
        f"/accounts/{shared['id']}", headers=ivan.headers, json={"name": "x"}
    )

    assert response.status_code == 403


async def test_holder_and_owner_can_rename_and_archive_a_personal_account(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    ivans = await create_account(client, ivan, name="Old name")

    renamed = await client.patch(
        f"/accounts/{ivans['id']}", headers=ivan.headers, json={"name": "New name"}
    )
    archived = await client.patch(
        f"/accounts/{ivans['id']}", headers=anna.headers, json={"archived": True}
    )

    assert renamed.json()["name"] == "New name"
    assert archived.json()["archived"] is True
    assert archived.json()["name"] == "New name"


async def test_archived_accounts_are_hidden_unless_asked_for(
    client: AsyncClient, anna: Actor
) -> None:
    account = await create_account(client, anna, name="Old card")
    await client.patch(f"/accounts/{account['id']}", headers=anna.headers, json={"archived": True})

    default = await client.get("/accounts", headers=anna.headers)
    everything = await client.get(
        "/accounts", headers=anna.headers, params={"include_archived": "true"}
    )

    assert default.json() == []
    assert [a["name"] for a in everything.json()] == ["Old card"]


async def test_get_one_account(client: AsyncClient, anna: Actor) -> None:
    account = await create_account(client, anna)

    response = await client.get(f"/accounts/{account['id']}", headers=anna.headers)

    assert response.status_code == 200
    assert response.json() == account


async def test_accounts_of_another_household_do_not_exist_for_outsiders(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    account = await create_account(client, anna)

    await assert_hidden_from(client, bob, "GET", f"/accounts/{account['id']}")
    await assert_hidden_from(client, bob, "PATCH", f"/accounts/{account['id']}", json={"name": "x"})
    listed = await client.get("/accounts", headers=bob.headers)
    assert listed.json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "type": "card", "currency": "BYN"},
        {"name": "   ", "type": "card", "currency": "BYN"},
        {"name": "x" * 101, "type": "card", "currency": "BYN"},
        {"name": "Card", "type": "crypto", "currency": "BYN"},
        {"name": "Card", "type": "card", "currency": "EUR"},
    ],
    ids=["empty-name", "blank-name", "long-name", "unknown-type", "unknown-currency"],
)
async def test_invalid_accounts_are_rejected(
    client: AsyncClient, anna: Actor, body: dict[str, str]
) -> None:
    response = await client.post("/accounts", headers=anna.headers, json=body)

    assert response.status_code == 422


async def test_an_owner_whose_household_has_accounts_cannot_join_another(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    await create_account(client, bob)
    code = (await client.post("/household/invites", headers=anna.headers)).json()["code"]

    response = await client.post(f"/household/invites/{code}/redeem", headers=bob.headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "household_not_empty"


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_accounts_require_authentication(client: AsyncClient, method: str) -> None:
    assert (await client.request(method, "/accounts")).status_code == 401


async def test_the_currency_of_an_account_cannot_be_changed(
    client: AsyncClient, anna: Actor
) -> None:
    account = await create_account(client, anna, currency="BYN")

    response = await client.patch(
        f"/accounts/{account['id']}", headers=anna.headers, json={"currency": "USD"}
    )

    assert response.status_code == 422
    unchanged = await client.get(f"/accounts/{account['id']}", headers=anna.headers)
    assert unchanged.json()["currency"] == "BYN"


async def test_the_type_of_an_account_can_be_changed(client: AsyncClient, anna: Actor) -> None:
    account = await create_account(client, anna, type="card")

    response = await client.patch(
        f"/accounts/{account['id']}", headers=anna.headers, json={"type": "savings"}
    )

    assert response.json()["type"] == "savings"
