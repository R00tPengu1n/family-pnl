from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.api.deps import get_rate_source
from tests.integration.helpers import Actor, assert_hidden_from, sign_up
from tests.integration.test_rate_service import RATES_TUESDAY, TUESDAY, FakeSource


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


async def account(client: AsyncClient, actor: Actor, currency: str, name: str = "") -> str:
    response = await client.post(
        "/accounts",
        headers=actor.headers,
        json={"name": name or f"{currency} card", "type": "card", "currency": currency},
    )
    assert response.status_code == 201, response.text
    account_id: str = response.json()["id"]
    return account_id


async def transfer(client: AsyncClient, actor: Actor, **fields: Any) -> Any:
    body = {"type": "transfer", "amount": "100", "operation_date": "2026-10-20", **fields}
    return await client.post("/operations", headers=actor.headers, json=body)


async def test_a_transfer_in_one_currency_moves_the_same_amount(
    client: AsyncClient, anna: Actor
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")

    response = await transfer(client, anna, account_id=card, target_account_id=cash)

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "transfer"
    assert body["category_id"] is None
    assert (body["amount"], body["currency"]) == ("100.00", "BYN")
    assert (body["target_amount"], body["target_currency"]) == ("100.00", "BYN")
    assert body["target_account_id"] == cash


async def test_a_transfer_between_currencies_converts_at_the_date_rate(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    usd, rub = await account(client, anna, "USD"), await account(client, anna, "RUB")

    response = await transfer(client, anna, account_id=usd, target_account_id=rub)

    body = response.json()
    assert (body["amount"], body["currency"]) == ("100.00", "USD")
    assert (body["target_amount"], body["target_currency"]) == ("8290.20", "RUB")
    assert source.calls == [TUESDAY]


async def test_the_target_amount_can_be_given_explicitly(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    usd, rub = await account(client, anna, "USD"), await account(client, anna, "RUB")

    response = await transfer(
        client, anna, account_id=usd, target_account_id=rub, target_amount="8200"
    )

    assert response.json()["target_amount"] == "8200.00"
    assert source.calls == []  # what the bank actually credited, no rate needed


async def test_one_currency_transfers_cannot_change_the_amount_on_the_way(
    client: AsyncClient, anna: Actor
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")

    response = await transfer(
        client, anna, account_id=card, target_account_id=cash, target_amount="90"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_operation"


async def test_a_transfer_to_the_same_account_is_rejected(client: AsyncClient, anna: Actor) -> None:
    card = await account(client, anna, "BYN")

    response = await transfer(client, anna, account_id=card, target_account_id=card)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "transfer_same_account"


@pytest.mark.parametrize(
    "extra",
    [{"category": True}, {"currency": "USD"}, {"no_target": True}],
    ids=["with-category", "other-currency", "without-target"],
)
async def test_malformed_transfers_are_rejected(
    client: AsyncClient, anna: Actor, extra: dict[str, Any]
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    fields: dict[str, Any] = {"account_id": card, "target_account_id": cash}
    if extra.get("category"):
        categories = (await client.get("/categories", headers=anna.headers)).json()
        fields["category_id"] = categories[0]["id"]
    if "currency" in extra:
        fields["currency"] = extra["currency"]
    if extra.get("no_target"):
        del fields["target_account_id"]

    response = await transfer(client, anna, **fields)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_operation"


async def test_an_expense_with_a_target_account_is_rejected(
    client: AsyncClient, anna: Actor
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    food = (
        await client.get("/categories", headers=anna.headers, params={"kind": "expense"})
    ).json()

    response = await client.post(
        "/operations",
        headers=anna.headers,
        json={
            "type": "expense",
            "amount": "5",
            "currency": "BYN",
            "account_id": card,
            "category_id": food[0]["id"],
            "target_account_id": cash,
        },
    )

    assert response.status_code == 422


async def test_an_expense_without_a_category_is_rejected(client: AsyncClient, anna: Actor) -> None:
    card = await account(client, anna, "BYN")

    response = await client.post(
        "/operations",
        headers=anna.headers,
        json={"type": "expense", "amount": "5", "currency": "BYN", "account_id": card},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_operation"


async def test_a_transfer_to_a_foreign_account_is_not_found(
    client: AsyncClient, anna: Actor
) -> None:
    bob = await sign_up(client, "bob@example.com")
    card, bobs = await account(client, anna, "BYN"), await account(client, bob, "BYN")

    response = await transfer(client, anna, account_id=card, target_account_id=bobs)

    assert response.status_code == 404


async def test_editing_the_amount_reconverts_a_transfer_between_currencies(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    usd, rub = await account(client, anna, "USD"), await account(client, anna, "RUB")
    created = (await transfer(client, anna, account_id=usd, target_account_id=rub)).json()

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"amount": "50"}
    )

    assert response.json()["target_amount"] == "4145.10"


async def test_editing_the_amount_of_a_one_currency_transfer_moves_both_sides(
    client: AsyncClient, anna: Actor
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    created = (await transfer(client, anna, account_id=card, target_account_id=cash)).json()

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"amount": "40"}
    )

    assert (response.json()["amount"], response.json()["target_amount"]) == ("40.00", "40.00")


async def test_the_target_amount_of_a_transfer_can_be_corrected(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    usd, rub = await account(client, anna, "USD"), await account(client, anna, "RUB")
    created = (await transfer(client, anna, account_id=usd, target_account_id=rub)).json()

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"target_amount": "8000"}
    )

    assert response.json()["target_amount"] == "8000.00"
    assert response.json()["amount"] == "100.00"


@pytest.mark.parametrize("field", ["account_id", "currency", "category_id"])
async def test_accounts_currencies_and_categories_of_a_transfer_are_fixed(
    client: AsyncClient, anna: Actor, field: str
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    created = (await transfer(client, anna, account_id=card, target_account_id=cash)).json()
    values = {"account_id": cash, "currency": "USD", "category_id": card}

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={field: values[field]}
    )

    assert response.status_code == 422


async def test_an_expense_has_no_target_amount_to_edit(client: AsyncClient, anna: Actor) -> None:
    card = await account(client, anna, "BYN")
    food = (
        await client.get("/categories", headers=anna.headers, params={"kind": "expense"})
    ).json()
    created = (
        await client.post(
            "/operations",
            headers=anna.headers,
            json={
                "type": "expense",
                "amount": "5",
                "currency": "BYN",
                "account_id": card,
                "category_id": food[0]["id"],
            },
        )
    ).json()

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"target_amount": "5"}
    )

    assert response.status_code == 422


async def test_transfers_of_another_household_do_not_exist_for_outsiders(
    client: AsyncClient, anna: Actor
) -> None:
    bob = await sign_up(client, "bob@example.com")
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    created = (await transfer(client, anna, account_id=card, target_account_id=cash)).json()

    await assert_hidden_from(client, bob, "GET", f"/operations/{created['id']}")


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE operations SET target_account_id = NULL",
            "ck_operations_target_iff_transfer",
        ),
        (
            "UPDATE operations SET target_account_id = account_id",
            "ck_operations_transfer_two_accounts",
        ),
        ("UPDATE operations SET target_amount = 0", "ck_operations_target_amount_positive"),
    ],
    ids=["no-target", "same-account", "zero-target"],
)
async def test_the_database_refuses_incomplete_transfers(
    client: AsyncClient, anna: Actor, db_session: AsyncSession, statement: str, constraint: str
) -> None:
    card, cash = await account(client, anna, "BYN"), await account(client, anna, "BYN", "Cash")
    await transfer(client, anna, account_id=card, target_account_id=cash)

    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_a_comment_change_keeps_a_transfer_untouched(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    usd, rub = await account(client, anna, "USD"), await account(client, anna, "RUB")
    created = (await transfer(client, anna, account_id=usd, target_account_id=rub)).json()

    response = await client.patch(
        f"/operations/{created['id']}", headers=anna.headers, json={"comment": "Обмен"}
    )

    assert response.json()["comment"] == "Обмен"
    assert response.json()["target_amount"] == created["target_amount"]
    assert source.calls == [TUESDAY]  # no second conversion
