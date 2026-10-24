"""Account balances in the account currency, from operations converted at their dates."""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from family_pnl.api.deps import get_rate_source
from family_pnl.core.clock import FrozenClock
from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import category_id, new_account, record
from tests.integration.test_rate_service import RATES_TUESDAY, TUESDAY, FakeSource


@pytest.fixture
def clock() -> FrozenClock:
    """Today is 2026-10-20, the day the fake rate source knows."""
    return FrozenClock(datetime(2026, 10, 20, 9, 0, tzinfo=UTC))


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


async def balances(client: AsyncClient, actor: Actor) -> dict[str, str]:
    response = await client.get("/accounts/balances", headers=actor.headers)
    assert response.status_code == 200, response.text
    return {b["name"]: b["balance"] for b in response.json()["accounts"]}


async def test_a_new_account_has_a_zero_balance(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    await new_account(client, anna, "BYN", "Card")

    assert await balances(client, anna) == {"Card": "0.00"}


async def test_balance_adds_incomes_and_transfers_in_and_subtracts_the_rest(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Card")
    cash = await new_account(client, anna, "BYN", "Cash")
    dollars = await new_account(client, anna, "USD", "Dollars")
    salary = await category_id(client, anna, "Зарплата")
    food = await category_id(client, anna, "Продукты")

    await record(
        client,
        anna,
        type="income",
        amount="100",
        currency="BYN",
        account_id=card,
        category_id=salary,
    )
    await record(
        client, anna, type="expense", amount="30", currency="BYN", account_id=card, category_id=food
    )
    # 300 RUB from a BYN card: 300 * 0.036127 = 10.8381 BYN at the date's rate.
    await record(
        client,
        anna,
        type="expense",
        amount="300",
        currency="RUB",
        account_id=card,
        category_id=food,
    )
    await record(
        client, anna, type="transfer", amount="20", account_id=card, target_account_id=cash
    )
    # 10 USD -> BYN card at 2.9950: 29.95 BYN arrive.
    await record(
        client,
        anna,
        type="income",
        amount="10",
        currency="USD",
        account_id=dollars,
        category_id=salary,
    )
    await record(
        client, anna, type="transfer", amount="10", account_id=dollars, target_account_id=card
    )

    # 100 - 30 - 10.8381 - 20 + 29.95 = 69.1119, rounded once.
    assert await balances(client, anna) == {"Card": "69.11", "Cash": "20.00", "Dollars": "0.00"}


async def test_rounding_happens_once_per_account(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Card")
    food = await category_id(client, anna, "Продукты")
    for _ in range(3):
        # 0.14 RUB = 0.00505778 BYN: rounded one by one 3 * 0.01 = 0.03; exact sum 0.0152 -> 0.02.
        await record(
            client,
            anna,
            type="expense",
            amount="0.14",
            currency="RUB",
            account_id=card,
            category_id=food,
        )

    assert await balances(client, anna) == {"Card": "-0.02"}


async def test_balances_cover_every_account_of_the_household(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    ivan = await join_household(client, anna, "ivan@example.com")
    await new_account(client, anna, "BYN", "Anna card")
    await new_account(client, ivan, "RUB", "Ivan card")

    for actor in (anna, ivan):
        assert set(await balances(client, actor)) == {"Anna card", "Ivan card"}


async def test_balances_of_another_household_are_never_included(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    bob = await sign_up(client, "bob@example.com")
    await new_account(client, anna, "BYN", "Anna card")

    assert await balances(client, bob) == {}


async def test_archived_accounts_keep_their_balance_but_are_listed_only_on_request(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Old card")
    salary = await category_id(client, anna, "Зарплата")
    await record(
        client, anna, type="income", amount="5", currency="BYN", account_id=card, category_id=salary
    )
    await client.patch(f"/accounts/{card}", headers=anna.headers, json={"archived": True})

    default = await balances(client, anna)
    everything = await client.get(
        "/accounts/balances", headers=anna.headers, params={"include_archived": "true"}
    )

    assert default == {}
    assert everything.json()["accounts"][0]["balance"] == "5.00"


async def test_one_currency_balances_need_no_rates(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Card")
    food = await category_id(client, anna, "Продукты")
    await record(
        client, anna, type="expense", amount="7", currency="BYN", account_id=card, category_id=food
    )
    await client.patch("/me/settings", headers=anna.headers, json={"display_currency": "BYN"})
    source.down = True

    assert await balances(client, anna) == {"Card": "-7.00"}
    assert source.calls == []


async def test_rates_are_fetched_once_per_date(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Card")
    usd = await new_account(client, anna, "USD", "Dollars")
    food = await category_id(client, anna, "Продукты")
    await record(
        client,
        anna,
        type="expense",
        amount="100",
        currency="RUB",
        account_id=card,
        category_id=food,
    )
    await record(
        client, anna, type="expense", amount="1", currency="RUB", account_id=usd, category_id=food
    )
    calls_before = len(source.calls)

    await balances(client, anna)

    # Two RUB flows on 2026-10-20 (one per account): a single lookup of that date's rates.
    assert len(source.calls) - calls_before <= 1
