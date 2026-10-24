"""Spending against limits, and 80% / 100% notifications written to the outbox."""

from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.api.deps import get_rate_source
from family_pnl.core.clock import FrozenClock
from family_pnl.domain.currency import Currency
from family_pnl.models import Household, Notification
from tests.integration.helpers import Actor, sign_up
from tests.integration.ledger_helpers import category_id, new_account, record
from tests.integration.test_rate_service import RATES_TUESDAY, TUESDAY, FakeSource


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))  # inside the November window


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def setup(
    client: AsyncClient, source: FakeSource, db_session: AsyncSession
) -> dict[str, Any]:
    """Anna with a BYN card and a 100 BYN limit on food for October 2026."""
    anna = await sign_up(client, "anna@example.com")
    # The settings endpoint arrives in Task 20; the base currency is set directly here.
    await db_session.execute(update(Household).values(base_currency=Currency.BYN))
    card = await new_account(client, anna, "BYN", "Card")
    food = await category_id(client, anna, "Продукты")
    taxi = await category_id(client, anna, "Транспорт")
    # The owner may plan October although its window has passed.
    response = await client.put(
        f"/budgets/2026-10/limits/{food}", headers=anna.headers, json={"amount": "100"}
    )
    assert response.status_code == 200, response.text
    return {"anna": anna, "card": card, "food": food, "taxi": taxi}


async def spend(
    client: AsyncClient, s: dict[str, Any], amount: str, **extra: Any
) -> dict[str, Any]:
    fields = {"currency": "BYN", "category_id": s["food"], **extra}
    return await record(
        client, s["anna"], type="expense", amount=amount, account_id=s["card"], **fields
    )


async def notifications(db_session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db_session.scalars(select(Notification).order_by(Notification.created_at))).all()
    return [row.payload for row in rows]


async def execution(client: AsyncClient, actor: Actor, month: str = "2026-10") -> dict[str, Any]:
    response = await client.get(f"/budgets/{month}/execution", headers=actor.headers)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def test_execution_shows_spent_and_remaining_per_category(
    client: AsyncClient, setup: dict[str, Any]
) -> None:
    await spend(client, setup, "30")
    # 300 RUB on 2026-10-20 = 10.8381 BYN.
    await spend(client, setup, "300", currency="RUB")

    found = await execution(client, setup["anna"])

    assert found["currency"] == "BYN"
    assert found["categories"] == [
        {
            "category_id": setup["food"],
            "category": "Продукты",
            "limit": "100.00",
            "spent": "40.84",
            "remaining": "59.16",
            "percent": "40.8",
        }
    ]


async def test_expenses_outside_the_month_or_category_do_not_count(
    client: AsyncClient, setup: dict[str, Any]
) -> None:
    await spend(client, setup, "50", operation_date="2026-09-30")
    await spend(client, setup, "50", operation_date="2026-11-01")
    await spend(client, setup, "50", category_id=setup["taxi"])

    assert (await execution(client, setup["anna"]))["categories"][0]["spent"] == "0.00"


async def test_a_month_without_a_budget_has_no_execution(
    client: AsyncClient, setup: dict[str, Any]
) -> None:
    found = await execution(client, setup["anna"], month="2027-05")

    assert found["categories"] == []


async def test_reaching_80_percent_writes_one_notification(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    await spend(client, setup, "79.99")
    assert await notifications(db_session) == []

    await spend(client, setup, "0.01")
    await spend(client, setup, "5")  # still between 80% and 100%: nothing new

    assert await notifications(db_session) == [
        {
            "month": "2026-10",
            "category_id": setup["food"],
            "threshold": 80,
            "spent": "80.00",
            "limit": "100.00",
            "currency": "BYN",
        }
    ]


async def test_jumping_past_100_percent_writes_both_thresholds_once(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    await spend(client, setup, "120")
    await spend(client, setup, "10")

    assert [n["threshold"] for n in await notifications(db_session)] == [80, 100]


async def test_editing_an_expense_up_can_cross_a_threshold(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    created = await spend(client, setup, "10")

    await client.patch(
        f"/operations/{created['id']}", headers=setup["anna"].headers, json={"amount": "85"}
    )

    assert [n["threshold"] for n in await notifications(db_session)] == [80]


async def test_falling_below_and_crossing_again_does_not_repeat_the_notification(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    created = await spend(client, setup, "90")
    await client.delete(f"/operations/{created['id']}", headers=setup["anna"].headers)

    await spend(client, setup, "90")

    assert [n["threshold"] for n in await notifications(db_session)] == [80]


async def test_categories_without_a_limit_never_notify(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    await spend(client, setup, "500", category_id=setup["taxi"])

    assert await notifications(db_session) == []


async def test_incomes_and_transfers_never_notify(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession
) -> None:
    salary = await category_id(client, setup["anna"], "Зарплата")
    cash = await new_account(client, setup["anna"], "BYN", "Cash")
    await record(
        client,
        setup["anna"],
        type="income",
        amount="500",
        currency="BYN",
        account_id=setup["card"],
        category_id=salary,
    )
    await record(
        client,
        setup["anna"],
        type="transfer",
        amount="500",
        account_id=setup["card"],
        target_account_id=cash,
    )

    assert await notifications(db_session) == []


async def test_without_rates_the_expense_is_recorded_and_the_check_is_skipped(
    client: AsyncClient, setup: dict[str, Any], db_session: AsyncSession, source: FakeSource
) -> None:
    source.down = True
    source.published.clear()

    with structlog.testing.capture_logs() as logs:
        created = await spend(client, setup, "900", currency="RUB", operation_date="2026-10-05")

    assert created["amount"] == "900.00"
    assert await notifications(db_session) == []
    assert "budget_thresholds_skipped" in [log["event"] for log in logs]


async def test_several_categories_share_one_rate_lookup_per_date(
    client: AsyncClient, setup: dict[str, Any]
) -> None:
    await client.put(
        f"/budgets/2026-10/limits/{setup['taxi']}",
        headers=setup["anna"].headers,
        json={"amount": "50"},
    )
    await spend(client, setup, "100", currency="RUB")
    await spend(client, setup, "200", currency="RUB", category_id=setup["taxi"])

    found = await execution(client, setup["anna"])

    # 100 RUB = 3.61 BYN, 200 RUB = 7.23 BYN, both at the rate of 2026-10-20.
    assert {c["category"]: c["spent"] for c in found["categories"]} == {
        "Продукты": "3.61",
        "Транспорт": "7.23",
    }
