"""Period reports: totals and breakdowns in each member's display currency."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from family_pnl.api.deps import get_rate_source
from family_pnl.core.clock import FrozenClock
from family_pnl.domain.currency import Currency
from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import category_id, new_account, record
from tests.integration.test_rate_service import RATES_MONDAY, RATES_TUESDAY, TUESDAY, FakeSource

SEPTEMBER_30 = date(2026, 9, 30)
OCTOBER_1 = date(2026, 10, 1)
TODAY = date(2026, 10, 25)
PERIOD = "/reports?from=2026-09-01&to=2026-10-31"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource(
        {
            SEPTEMBER_30: RATES_MONDAY,
            OCTOBER_1: RATES_TUESDAY,
            TUESDAY: RATES_TUESDAY,
            TODAY: {Currency.USD: Decimal("3.0000"), Currency.RUB: Decimal("0.036000")},
        }
    )
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def family(client: AsyncClient, source: FakeSource) -> dict[str, Any]:
    """Anna (owner) and Ivan in a BYN household; Ivan reads reports in USD."""
    anna = await sign_up(client, "anna@example.com")
    ivan = await join_household(client, anna, "ivan@example.com")
    await client.patch("/household/settings", headers=anna.headers, json={"base_currency": "BYN"})
    await client.patch("/me/settings", headers=ivan.headers, json={"display_currency": "USD"})
    card = await new_account(client, anna, "BYN", "Card")
    dollars = await new_account(client, ivan, "USD", "Dollars")
    food = await category_id(client, anna, "Продукты")
    taxi = await category_id(client, anna, "Транспорт")
    salary = await category_id(client, anna, "Зарплата")
    byn = {"currency": "BYN", "account_id": card}
    await record(client, anna, type="income", amount="2995", category_id=salary, **byn)
    await record(client, anna, type="expense", amount="30", category_id=food, **byn)
    await record(
        client,
        ivan,
        type="expense",
        amount="100",
        currency="USD",
        account_id=dollars,
        category_id=food,
    )
    await record(
        client,
        ivan,
        type="expense",
        amount="50",
        category_id=taxi,
        operation_date="2026-09-30",
        **byn,
    )
    # A transfer moves money inside the household: it is not an income or an expense.
    await record(
        client, anna, type="transfer", amount="10", account_id=card, target_account_id=dollars
    )
    response = await client.put(
        f"/budgets/2026-10/limits/{food}", headers=anna.headers, json={"amount": "400"}
    )
    assert response.status_code == 200, response.text
    return {"anna": anna, "ivan": ivan, "food": food, "taxi": taxi, "salary": salary}


async def report(client: AsyncClient, actor: Actor, path: str = PERIOD) -> dict[str, Any]:
    response = await client.get(path, headers=actor.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def totals(income: str, expense: str, net: str) -> dict[str, str]:
    return {"income": income, "expense": expense, "net": net}


async def test_the_report_in_the_base_currency(client: AsyncClient, family: dict[str, Any]) -> None:
    anna, ivan = family["anna"], family["ivan"]

    found = await report(client, anna)

    assert (found["date_from"], found["date_to"], found["currency"]) == (
        "2026-09-01",
        "2026-10-31",
        "BYN",
    )
    # 100 USD at 2.9950 on 2026-10-20 = 299.50 BYN.
    assert found["totals"] == totals("2995.00", "379.50", "2615.50")
    assert found["by_category"] == [
        {
            "category_id": family["salary"],
            "category": "Зарплата",
            "kind": "income",
            "amount": "2995.00",
        },
        {
            "category_id": family["food"],
            "category": "Продукты",
            "kind": "expense",
            "amount": "329.50",
        },
        {
            "category_id": family["taxi"],
            "category": "Транспорт",
            "kind": "expense",
            "amount": "50.00",
        },
    ]
    assert found["by_member"] == [
        {
            "user_id": str(anna.user_id),
            "name": anna.email,
            "totals": totals("2995.00", "30.00", "2965.00"),
        },
        {
            "user_id": str(ivan.user_id),
            "name": ivan.email,
            "totals": totals("0.00", "349.50", "-349.50"),
        },
    ]
    assert found["by_month"] == [
        {"month": "2026-09", "totals": totals("0.00", "50.00", "-50.00")},
        {"month": "2026-10", "totals": totals("2995.00", "329.50", "2665.50")},
    ]
    assert found["plan_vs_actual"] == [
        {
            "month": "2026-10",
            "category_id": family["food"],
            "category": "Продукты",
            "planned": "400.00",
            "actual": "329.50",
            "remaining": "70.50",
        }
    ]


async def test_another_member_sees_the_same_report_in_their_display_currency(
    client: AsyncClient, family: dict[str, Any]
) -> None:
    found = await report(client, family["ivan"])

    assert found["currency"] == "USD"
    # 2995 BYN / 2.9950 = 1000 USD; 30 BYN = 10.0167 USD; 50 BYN at 2.9910 = 16.7168 USD.
    assert found["totals"] == totals("1000.00", "126.73", "873.27")
    assert [c["amount"] for c in found["by_category"]] == ["1000.00", "110.02", "16.72"]
    assert [m["totals"] for m in found["by_month"]] == [
        totals("0.00", "16.72", "-16.72"),
        totals("1000.00", "110.02", "889.98"),
    ]
    # The October limit is converted at the rate of 1 October: 400 / 2.9950.
    plan = found["plan_vs_actual"][0]
    assert (plan["planned"], plan["actual"], plan["remaining"]) == ("133.56", "110.02", "23.54")


async def test_a_limit_of_a_month_not_started_is_converted_at_todays_rate(
    client: AsyncClient, family: dict[str, Any]
) -> None:
    anna, ivan = family["anna"], family["ivan"]
    await client.put(
        f"/budgets/2026-11/limits/{family['taxi']}", headers=anna.headers, json={"amount": "300"}
    )

    found = await report(client, ivan, "/reports?from=2026-11-01&to=2026-11-30")

    assert found["totals"] == totals("0.00", "0.00", "0.00")
    assert found["by_category"] == found["by_member"] == found["by_month"] == []
    # 300 BYN at today's 3.0000.
    assert [(p["month"], p["planned"], p["actual"]) for p in found["plan_vs_actual"]] == [
        ("2026-11", "100.00", "0.00")
    ]


async def test_operations_outside_the_period_are_left_out(
    client: AsyncClient, family: dict[str, Any]
) -> None:
    found = await report(client, family["anna"], "/reports?from=2026-10-20&to=2026-10-20")

    assert found["totals"] == totals("2995.00", "329.50", "2665.50")
    assert [m["month"] for m in found["by_month"]] == ["2026-10"]


async def test_a_one_day_period_on_the_edge_counts_that_day(
    client: AsyncClient, family: dict[str, Any]
) -> None:
    found = await report(client, family["anna"], "/reports?from=2026-09-30&to=2026-09-30")

    assert found["totals"] == totals("0.00", "50.00", "-50.00")
    assert found["plan_vs_actual"] == []


async def test_other_households_see_nothing(client: AsyncClient, family: dict[str, Any]) -> None:
    bob = await sign_up(client, "bob@example.com")

    found = await report(client, bob)

    assert found["totals"] == totals("0.00", "0.00", "0.00")
    assert found["by_category"] == found["plan_vs_actual"] == []


@pytest.mark.parametrize(
    "query",
    ["from=2026-10-02&to=2026-10-01", "from=2026-01-01&to=2027-01-02"],
    ids=["reversed", "longer-than-366-days"],
)
async def test_invalid_periods_are_rejected(client: AsyncClient, query: str) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.get(f"/reports?{query}", headers=anna.headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_period"


async def test_a_period_of_366_days_is_accepted(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.get("/reports?from=2026-01-01&to=2027-01-01", headers=anna.headers)

    assert response.status_code == 200


@pytest.mark.parametrize("query", ["", "from=2026-10-01", "from=2026-10-01&to=yesterday"])
async def test_both_dates_are_required(client: AsyncClient, query: str) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.get(f"/reports?{query}", headers=anna.headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


async def test_reports_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(PERIOD)).status_code == 401
