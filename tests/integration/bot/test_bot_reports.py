"""Switching the display currency in the bot changes the next report (real API)."""

from datetime import UTC, datetime

from fastapi import FastAPI

from family_pnl.api.deps import get_rate_source
from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.reports import Reports
from tests.integration.test_rate_service import RATES_TUESDAY, TUESDAY, FakeSource

ANNA = 5000000001


async def test_the_report_follows_the_currency_chosen_in_the_bot(
    api: ApiClient, app: FastAPI
) -> None:
    app.dependency_overrides[get_rate_source] = lambda: FakeSource({TUESDAY: RATES_TUESDAY})
    await api.register(ANNA, display_name="Анна")
    card = await api.request(
        ANNA, "POST", "/accounts", json={"name": "Card", "type": "card", "currency": "BYN"}
    )
    food = next(
        c["id"]
        for c in await api.request(ANNA, "GET", "/categories", params={"kind": "expense"})
        if c["name"] == "Продукты"
    )
    await api.request(
        ANNA,
        "POST",
        "/operations",
        json={
            "type": "expense",
            "amount": "299.50",
            "currency": "BYN",
            "account_id": card["id"],
            "category_id": food,
            "operation_date": "2026-10-20",
        },
    )
    reports = Reports(api, now=lambda: datetime(2026, 10, 25, 9, 0, tzinfo=UTC))

    await reports.set_currency(ANNA, "cur:BYN")
    in_byn = (await reports.report(ANNA)).text
    await reports.set_currency(ANNA, "cur:USD")
    in_usd = (await reports.report(ANNA)).text

    assert in_byn.splitlines()[:3] == ["Октябрь 2026, BYN", "Доходы: 0.00", "Расходы: 299.50"]
    # 299.50 BYN at 2.9950 on 2026-10-20.
    assert in_usd.splitlines()[:3] == ["Октябрь 2026, USD", "Доходы: 0.00", "Расходы: 100.00"]
    assert (await api.request(ANNA, "GET", "/me/settings"))["display_currency"] == "USD"
