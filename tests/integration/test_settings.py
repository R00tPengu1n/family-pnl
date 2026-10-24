"""Household settings (owner) and member currency preferences."""

from datetime import UTC, datetime
from typing import Any

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
    """Today is 2026-10-20 in Minsk: the fake rate source knows this day."""
    return FrozenClock(datetime(2026, 10, 20, 9, 0, tzinfo=UTC))


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


@pytest.fixture
async def ivan(client: AsyncClient, anna: Actor) -> Actor:
    return await join_household(client, anna, "ivan@example.com")


async def get(client: AsyncClient, actor: Actor, path: str) -> dict[str, Any]:
    response = await client.get(path, headers=actor.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_household_settings_default_to_rub_and_minsk(
    client: AsyncClient, anna: Actor
) -> None:
    assert await get(client, anna, "/household/settings") == {
        "name": "Family",
        "base_currency": "RUB",
        "timezone": "Europe/Minsk",
    }


async def test_the_owner_changes_household_settings(client: AsyncClient, anna: Actor) -> None:
    response = await client.patch(
        "/household/settings",
        headers=anna.headers,
        json={"base_currency": "BYN", "timezone": "Europe/Moscow", "name": "Ivanovs"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Ivanovs",
        "base_currency": "BYN",
        "timezone": "Europe/Moscow",
    }
    me = await get(client, anna, "/me")
    assert me["household"]["base_currency"] == "BYN"


async def test_a_member_cannot_change_household_settings(client: AsyncClient, ivan: Actor) -> None:
    response = await client.patch(
        "/household/settings", headers=ivan.headers, json={"base_currency": "USD"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [{"base_currency": "EUR"}, {"timezone": "Mars/Olympus"}, {"name": "  "}, {"color": "red"}],
    ids=["currency", "timezone", "blank-name", "unknown-field"],
)
async def test_invalid_household_settings_are_rejected(
    client: AsyncClient, anna: Actor, body: dict[str, str]
) -> None:
    response = await client.patch("/household/settings", headers=anna.headers, json=body)

    assert response.status_code == 422


async def test_member_currencies_default_to_the_household_base(
    client: AsyncClient, ivan: Actor
) -> None:
    assert await get(client, ivan, "/me/settings") == {
        "display_currency": "RUB",
        "input_currency": "RUB",
        "display_currency_set": False,
        "input_currency_set": False,
    }


async def test_each_member_chooses_their_own_currencies(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    await client.patch(
        "/me/settings",
        headers=ivan.headers,
        json={"display_currency": "USD", "input_currency": "BYN"},
    )

    ivans = await get(client, ivan, "/me/settings")
    annas = await get(client, anna, "/me/settings")
    assert (ivans["display_currency"], ivans["input_currency"]) == ("USD", "BYN")
    assert (annas["display_currency"], annas["input_currency"]) == ("RUB", "RUB")


async def test_a_member_can_return_to_the_household_default(
    client: AsyncClient, ivan: Actor
) -> None:
    await client.patch("/me/settings", headers=ivan.headers, json={"display_currency": "USD"})

    await client.patch("/me/settings", headers=ivan.headers, json={"display_currency": None})

    assert (await get(client, ivan, "/me/settings"))["display_currency_set"] is False


async def test_balances_total_in_the_members_display_currency(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    card = await new_account(client, anna, "BYN", "Card")
    usd = await new_account(client, anna, "USD", "Dollars")
    salary = await category_id(client, anna, "Зарплата")
    await record(
        client,
        anna,
        type="income",
        amount="299.50",
        currency="BYN",
        account_id=card,
        category_id=salary,
    )
    await record(
        client,
        anna,
        type="income",
        amount="100",
        currency="USD",
        account_id=usd,
        category_id=salary,
    )
    await client.patch("/me/settings", headers=anna.headers, json={"display_currency": "USD"})

    body = await get(client, anna, "/accounts/balances")

    # 299.50 BYN = 100 USD at today's 2.9950, plus 100 USD.
    assert (body["display_currency"], body["total"]) == ("USD", "200.00")
    assert {a["name"]: a["balance"] for a in body["accounts"]} == {
        "Card": "299.50",
        "Dollars": "100.00",
    }


async def test_settings_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/me/settings")).status_code == 401
    assert (await client.get("/household/settings")).status_code == 401


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": "Ivanovs"}, ("Ivanovs", "RUB", "Europe/Minsk")),
        ({"base_currency": "USD"}, ("Family", "USD", "Europe/Minsk")),
        ({"timezone": "Europe/Warsaw"}, ("Family", "RUB", "Europe/Warsaw")),
    ],
    ids=["name", "currency", "timezone"],
)
async def test_one_household_setting_changes_alone(
    client: AsyncClient, anna: Actor, change: dict[str, str], expected: tuple[str, str, str]
) -> None:
    body = (await client.patch("/household/settings", headers=anna.headers, json=change)).json()

    assert (body["name"], body["base_currency"], body["timezone"]) == expected
