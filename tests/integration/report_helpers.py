"""A household with a known report, shared by the report and export tests.

The clock of these tests is 2026-10-25 09:00 UTC (TODAY).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from family_pnl.api.deps import get_rate_source
from family_pnl.domain.currency import Currency
from tests.integration.helpers import join_household, sign_up
from tests.integration.ledger_helpers import category_id, new_account, record
from tests.integration.test_rate_service import RATES_MONDAY, RATES_TUESDAY, TUESDAY, FakeSource

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
SEPTEMBER_30 = date(2026, 9, 30)
OCTOBER_1 = date(2026, 10, 1)
TODAY = date(2026, 10, 25)
PERIOD = "/reports?from=2026-09-01&to=2026-10-31"


def install_rates(app: FastAPI) -> FakeSource:
    """Rates for every date the family's report needs."""
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


async def build_family(client: AsyncClient) -> dict[str, Any]:
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
