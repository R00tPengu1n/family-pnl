from typing import Any

import pytest
from httpx import AsyncClient

from family_pnl.core.clock import FrozenClock
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


async def account_of(client: AsyncClient, actor: Actor, currency: str = "BYN") -> str:
    response = await client.post(
        "/accounts",
        headers=actor.headers,
        json={"name": f"{actor.email} {currency}", "type": "card", "currency": currency},
    )
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def category(client: AsyncClient, actor: Actor, name: str) -> str:
    found = (await client.get("/categories", headers=actor.headers)).json()
    return str(next(c["id"] for c in found if c["name"] == name))


async def expense(client: AsyncClient, actor: Actor, **fields: Any) -> Any:
    body = {"type": "expense", "amount": "12.50", "currency": "BYN", **fields}
    if "account_id" not in body:
        body["account_id"] = await account_of(client, actor)
    if "category_id" not in body:
        body["category_id"] = await category(client, actor, "Продукты")
    return await client.post("/operations", headers=actor.headers, json=body)


async def test_an_expense_is_recorded_as_entered(client: AsyncClient, anna: Actor) -> None:
    response = await expense(client, anna, comment="Молоко", operation_date="2026-10-20")

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "expense"
    assert body["amount"] == "12.50"
    assert body["currency"] == "BYN"
    assert body["operation_date"] == "2026-10-20"
    assert body["comment"] == "Молоко"
    assert body["author_id"] == str(anna.user_id)


async def test_the_date_defaults_to_today_in_the_household_time_zone(
    client: AsyncClient, anna: Actor, clock: FrozenClock
) -> None:
    clock.set(clock.now().replace(year=2026, month=10, day=19, hour=22, minute=30))

    response = await expense(client, anna)

    assert response.json()["operation_date"] == "2026-10-20"  # 01:30 in Minsk


async def test_an_operation_may_use_another_currency_than_its_account(
    client: AsyncClient, anna: Actor
) -> None:
    response = await expense(client, anna, currency="RUB", amount="300")

    assert response.status_code == 201
    assert (response.json()["amount"], response.json()["currency"]) == ("300.00", "RUB")


async def test_an_income_needs_an_income_category(client: AsyncClient, anna: Actor) -> None:
    salary = await category(client, anna, "Зарплата")

    good = await expense(client, anna, type="income", category_id=salary, amount="2500")
    bad = await expense(client, anna, type="income")  # "Продукты" is an expense category

    assert good.status_code == 201
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "category_kind_mismatch"


@pytest.mark.parametrize(
    "amount", ["0", "-5", "1.005", "abc", "1e400", "1234567890123.45"], ids=str
)
async def test_invalid_amounts_are_rejected(client: AsyncClient, anna: Actor, amount: str) -> None:
    response = await expense(client, anna, amount=amount)

    assert response.status_code == 422


async def test_foreign_account_or_category_is_not_found(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    bobs_account = await account_of(client, bob)
    bobs_category = await category(client, bob, "Продукты")

    with_account = await expense(client, anna, account_id=bobs_account)
    with_category = await expense(client, anna, category_id=bobs_category)

    assert with_account.status_code == with_category.status_code == 404


async def test_archived_accounts_and_categories_cannot_take_new_operations(
    client: AsyncClient, anna: Actor
) -> None:
    account = await account_of(client, anna)
    await client.patch(f"/accounts/{account}", headers=anna.headers, json={"archived": True})

    response = await expense(client, anna, account_id=account)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "archived"


async def test_the_author_edits_an_operation(client: AsyncClient, anna: Actor) -> None:
    created = (await expense(client, anna)).json()

    response = await client.patch(
        f"/operations/{created['id']}",
        headers=anna.headers,
        json={"amount": "15.00", "comment": "Молоко и хлеб", "operation_date": "2026-10-21"},
    )

    assert response.status_code == 200
    assert response.json()["amount"] == "15.00"
    assert response.json()["comment"] == "Молоко и хлеб"
    assert response.json()["operation_date"] == "2026-10-21"


async def test_editing_rechecks_the_category_kind(client: AsyncClient, anna: Actor) -> None:
    created = (await expense(client, anna)).json()
    salary = await category(client, anna, "Зарплата")

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"category_id": salary}
    )

    assert response.status_code == 422


async def test_a_member_cannot_change_or_delete_another_members_operation(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    created = (await expense(client, anna)).json()

    edited = await client.patch(
        f"/operations/{created['id']}", headers=ivan.headers, json={"amount": "1"}
    )
    deleted = await client.delete(f"/operations/{created['id']}", headers=ivan.headers)

    assert edited.status_code == deleted.status_code == 403


async def test_the_owner_deletes_a_members_operation(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    created = (await expense(client, ivan)).json()

    response = await client.delete(f"/operations/{created['id']}", headers=anna.headers)

    assert response.status_code == 204
    gone = await client.get(f"/operations/{created['id']}", headers=anna.headers)
    assert gone.status_code == 404


async def test_household_members_see_each_others_operations(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    created = (await expense(client, ivan)).json()

    response = await client.get(f"/operations/{created['id']}", headers=anna.headers)

    assert response.json() == created


async def test_operations_of_another_household_do_not_exist_for_outsiders(
    client: AsyncClient, anna: Actor, bob: Actor
) -> None:
    created = (await expense(client, anna)).json()
    path = f"/operations/{created['id']}"

    await assert_hidden_from(client, bob, "GET", path)
    await assert_hidden_from(client, bob, "PATCH", path, json={"amount": "1"})
    await assert_hidden_from(client, bob, "DELETE", path)


async def test_operations_require_authentication(client: AsyncClient) -> None:
    assert (await client.post("/operations", json={})).status_code == 401


async def test_an_operation_moves_to_another_account_and_currency(
    client: AsyncClient, anna: Actor
) -> None:
    created = (await expense(client, anna)).json()
    usd_account = await account_of(client, anna, currency="USD")

    response = await client.patch(
        f"/operations/{created['id']}",
        headers=anna.headers,
        json={"account_id": usd_account, "currency": "USD"},
    )

    assert response.json()["account_id"] == usd_account
    assert response.json()["currency"] == "USD"
    assert response.json()["amount"] == created["amount"]  # untouched fields stay


async def test_an_archived_category_cannot_take_new_operations(
    client: AsyncClient, anna: Actor
) -> None:
    food = await category(client, anna, "Продукты")
    await client.patch(f"/categories/{food}", headers=anna.headers, json={"archived": True})

    response = await expense(client, anna, category_id=food)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "archived"


async def test_an_operation_moves_to_another_category_of_its_kind(
    client: AsyncClient, anna: Actor
) -> None:
    created = (await expense(client, anna)).json()
    cafe = await category(client, anna, "Кафе и рестораны")

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"category_id": cafe}
    )

    assert response.json()["category_id"] == cafe


async def test_unknown_fields_and_blank_comments_on_create(
    client: AsyncClient, anna: Actor
) -> None:
    fields = {
        "type": "expense",
        "amount": "1",
        "currency": "BYN",
        "account_id": await account_of(client, anna),
        "category_id": await category(client, anna, "Продукты"),
    }

    typo = await client.post("/operations", headers=anna.headers, json={**fields, "commnet": "x"})
    blank = await client.post("/operations", headers=anna.headers, json={**fields, "comment": "  "})

    assert typo.status_code == 422
    assert blank.status_code == 201
    assert blank.json()["comment"] is None
