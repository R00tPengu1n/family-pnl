"""GET /operations: filters, newest first, limit/offset pagination."""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import category_id, new_account, record


@pytest.fixture
async def household(client: AsyncClient) -> dict[str, Any]:
    """Anna and Ivan, a BYN card, a RUB card, and five operations over three days."""
    anna = await sign_up(client, "anna@example.com")
    ivan = await join_household(client, anna, "ivan@example.com")
    byn = await new_account(client, anna, "BYN", "BYN card")
    rub = await new_account(client, ivan, "RUB", "RUB card")
    food = await category_id(client, anna, "Продукты")
    taxi = await category_id(client, anna, "Транспорт")
    salary = await category_id(client, anna, "Зарплата")
    ops = {
        "milk": await record(
            client,
            anna,
            type="expense",
            amount="3",
            currency="BYN",
            account_id=byn,
            category_id=food,
            operation_date="2026-10-18",
        ),
        "taxi": await record(
            client,
            ivan,
            type="expense",
            amount="300",
            currency="RUB",
            account_id=rub,
            category_id=taxi,
            operation_date="2026-10-19",
        ),
        "bread": await record(
            client,
            ivan,
            type="expense",
            amount="2",
            currency="BYN",
            account_id=byn,
            category_id=food,
            operation_date="2026-10-19",
        ),
        "salary": await record(
            client,
            anna,
            type="income",
            amount="2500",
            currency="BYN",
            account_id=byn,
            category_id=salary,
            operation_date="2026-10-20",
        ),
        "move": await record(
            client,
            anna,
            type="transfer",
            amount="100",
            account_id=byn,
            target_account_id=await new_account(client, anna, "BYN", "Cash"),
            operation_date="2026-10-20",
        ),
    }
    return {"anna": anna, "ivan": ivan, "byn": byn, "rub": rub, "food": food, "ops": ops}


async def listed(client: AsyncClient, actor: Actor, **params: Any) -> dict[str, Any]:
    response = await client.get("/operations", headers=actor.headers, params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def names(page: dict[str, Any], household: dict[str, Any]) -> list[str]:
    by_id = {op["id"]: name for name, op in household["ops"].items()}
    return [by_id[item["id"]] for item in page["items"]]


async def test_all_operations_newest_first(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(client, household["anna"])

    assert page["total"] == 5
    assert names(page, household)[:2] in (["salary", "move"], ["move", "salary"])
    assert names(page, household)[-1] == "milk"


async def test_filter_by_period_is_inclusive(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    page = await listed(client, household["anna"], date_from="2026-10-19", date_to="2026-10-19")

    assert sorted(names(page, household)) == ["bread", "taxi"]


async def test_filter_by_category(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(client, household["anna"], category_id=household["food"])

    assert sorted(names(page, household)) == ["bread", "milk"]


async def test_filter_by_account_includes_transfers_to_and_from_it(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    page = await listed(client, household["anna"], account_id=household["byn"])

    assert sorted(names(page, household)) == ["bread", "milk", "move", "salary"]


async def test_filter_by_member(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(client, household["anna"], author_id=str(household["ivan"].user_id))

    assert sorted(names(page, household)) == ["bread", "taxi"]


async def test_filter_by_currency(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(client, household["anna"], currency="RUB")

    assert names(page, household) == ["taxi"]


async def test_filter_by_type(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(client, household["anna"], type="income")

    assert names(page, household) == ["salary"]


async def test_filters_combine(client: AsyncClient, household: dict[str, Any]) -> None:
    page = await listed(
        client,
        household["anna"],
        category_id=household["food"],
        author_id=str(household["ivan"].user_id),
        date_from="2026-10-18",
    )

    assert names(page, household) == ["bread"]


async def test_pages_split_the_list_without_overlap(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    first = await listed(client, household["anna"], limit=2, offset=0)
    second = await listed(client, household["anna"], limit=2, offset=2)
    third = await listed(client, household["anna"], limit=2, offset=4)

    seen = names(first, household) + names(second, household) + names(third, household)
    assert sorted(seen) == sorted(household["ops"])
    assert (first["limit"], first["offset"], first["total"]) == (2, 0, 5)
    assert len(third["items"]) == 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_page_size_is_capped(
    client: AsyncClient, household: dict[str, Any], params: dict[str, int]
) -> None:
    response = await client.get("/operations", headers=household["anna"].headers, params=params)

    assert response.status_code == 422


async def test_another_household_sees_nothing(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    bob = await sign_up(client, "bob@example.com")

    page = await listed(client, bob)

    assert (page["total"], page["items"]) == (0, [])


async def test_filtering_by_a_foreign_account_finds_nothing(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    bob = await sign_up(client, "bob@example.com")

    page = await listed(client, bob, account_id=household["byn"])

    assert page["total"] == 0
