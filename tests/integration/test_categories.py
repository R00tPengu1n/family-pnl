from typing import Any

import pytest
from httpx import AsyncClient

from family_pnl.domain.ledger import DEFAULT_CATEGORIES
from tests.integration.helpers import Actor, assert_hidden_from, join_household, sign_up


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


@pytest.fixture
async def ivan(client: AsyncClient, anna: Actor) -> Actor:
    return await join_household(client, anna, "ivan@example.com")


@pytest.fixture
async def bob(client: AsyncClient) -> Actor:
    return await sign_up(client, "bob@example.com")


async def categories(client: AsyncClient, actor: Actor, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/categories", headers=actor.headers, params=params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


async def create(client: AsyncClient, actor: Actor, name: str, kind: str = "expense") -> Any:
    return await client.post(
        "/categories", headers=actor.headers, json={"name": name, "kind": kind}
    )


async def test_a_new_household_has_the_default_categories(client: AsyncClient, anna: Actor) -> None:
    found = await categories(client, anna)

    assert sorted((c["kind"], c["name"]) for c in found) == sorted(
        (kind.value, name) for kind, name in DEFAULT_CATEGORIES
    )
    assert all(c["default"] is True for c in found)


async def test_a_household_registered_through_the_bot_has_them_too(client: AsyncClient) -> None:
    from tests.integration.conftest import BOT_SECRET

    bot = {"X-Bot-Token": BOT_SECRET}
    await client.post("/bot/register", headers=bot, json={"telegram_id": 5_000_000_001})
    token = (
        await client.post("/auth/telegram", headers=bot, json={"telegram_id": 5_000_000_001})
    ).json()["access_token"]

    response = await client.get("/categories", headers={"Authorization": f"Bearer {token}"})

    assert len(response.json()) == len(DEFAULT_CATEGORIES)


async def test_categories_are_filtered_by_kind(client: AsyncClient, anna: Actor) -> None:
    income = await categories(client, anna, kind="income")

    assert {c["name"] for c in income} == {"Зарплата", "Подработка", "Подарки", "Другое"}
    assert {c["kind"] for c in income} == {"income"}


async def test_a_member_adds_a_category_everyone_sees(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    response = await create(client, ivan, "  Спорт ")

    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Спорт"
    assert created["default"] is False
    assert "Спорт" in {c["name"] for c in await categories(client, anna, kind="expense")}


async def test_names_are_unique_per_kind_ignoring_case(client: AsyncClient, anna: Actor) -> None:
    duplicate = await create(client, anna, "продукты")
    other_kind = await create(client, anna, "Продукты", kind="income")

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "category_exists"
    assert other_kind.status_code == 201


async def test_names_may_repeat_across_households(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    assert (await create(client, anna, "Спорт")).status_code == 201
    assert (await create(client, bob, "Спорт")).status_code == 201


async def test_the_author_renames_and_archives_a_category(client: AsyncClient, ivan: Actor) -> None:
    category = (await create(client, ivan, "Спорт")).json()

    renamed = await client.patch(
        f"/categories/{category['id']}", headers=ivan.headers, json={"name": "Фитнес"}
    )
    archived = await client.patch(
        f"/categories/{category['id']}", headers=ivan.headers, json={"archived": True}
    )

    assert renamed.json()["name"] == "Фитнес"
    assert archived.json()["archived"] is True
    names = {c["name"] for c in await categories(client, ivan)}
    assert "Фитнес" not in names
    everything = {c["name"] for c in await categories(client, ivan, include_archived="true")}
    assert "Фитнес" in everything


async def test_renaming_into_an_existing_name_is_a_conflict(
    client: AsyncClient, anna: Actor
) -> None:
    category = (await create(client, anna, "Спорт")).json()

    response = await client.patch(
        f"/categories/{category['id']}", headers=anna.headers, json={"name": "ТРАНСПОРТ"}
    )

    assert response.status_code == 409


async def test_a_member_cannot_change_default_or_others_categories(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    default = (await categories(client, anna))[0]
    annas = (await create(client, anna, "Спорт")).json()

    for category in (default, annas):
        response = await client.patch(
            f"/categories/{category['id']}", headers=ivan.headers, json={"name": "x"}
        )
        assert response.status_code == 403


async def test_the_owner_renames_a_default_category(client: AsyncClient, anna: Actor) -> None:
    default = next(c for c in await categories(client, anna) if c["name"] == "Дети")

    response = await client.patch(
        f"/categories/{default['id']}", headers=anna.headers, json={"name": "Дочка"}
    )

    assert response.json()["name"] == "Дочка"


async def test_categories_of_another_household_do_not_exist_for_outsiders(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    category = (await create(client, anna, "Спорт")).json()

    await assert_hidden_from(
        client, bob, "PATCH", f"/categories/{category['id']}", json={"name": "x"}
    )
    assert "Спорт" not in {c["name"] for c in await categories(client, bob)}


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "kind": "expense"},
        {"name": "  ", "kind": "expense"},
        {"name": "x" * 51, "kind": "expense"},
        {"name": "Спорт", "kind": "transfer"},
    ],
    ids=["empty", "blank", "too-long", "unknown-kind"],
)
async def test_invalid_categories_are_rejected(
    client: AsyncClient, anna: Actor, body: dict[str, str]
) -> None:
    response = await client.post("/categories", headers=anna.headers, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_categories_require_authentication(client: AsyncClient, method: str) -> None:
    assert (await client.request(method, "/categories")).status_code == 401
