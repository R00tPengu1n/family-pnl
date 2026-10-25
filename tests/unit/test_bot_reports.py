"""/balance, /report and /currency replies with a fake API client."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.formatting import amount, money, month_name
from family_pnl_bot.quick_entry import Button, Reply
from family_pnl_bot.reports import Reports

ME = 1
OCTOBER_25 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)

REPORT = {
    "currency": "BYN",
    "totals": {"income": "2995.00", "expense": "379.50", "net": "2615.50"},
    "by_category": [
        {"category": "Зарплата", "kind": "income", "amount": "2995.00"},
        {"category": "Продукты", "kind": "expense", "amount": "329.50"},
        {"category": "Транспорт", "kind": "expense", "amount": "50.00"},
    ],
    "plan_vs_actual": [{"category": "Продукты", "planned": "400.00", "actual": "329.50"}],
}
EMPTY_REPORT = {
    "currency": "USD",
    "totals": {"income": "0.00", "expense": "0.00", "net": "0.00"},
    "by_category": [],
    "plan_vs_actual": [],
}


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.answers: dict[str, Any] = {
            "/household/settings": {"timezone": "Europe/Minsk"},
            "/reports": REPORT,
            "/me/settings": {"display_currency": "BYN"},
            "/accounts/balances": {
                "display_currency": "USD",
                "total": "1200.00",
                "accounts": [
                    {"name": "Card", "currency": "BYN", "balance": "2995.00"},
                    {"name": "Dollars", "currency": "USD", "balance": "200.00"},
                ],
            },
        }
        self.failure: ApiError | None = None

    async def request(
        self,
        telegram_id: int,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        if self.failure is not None:
            raise self.failure
        self.calls.append((method, path, json or params))
        return None if method == "PATCH" else self.answers[path]


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def reports(api: FakeApi, now: datetime = OCTOBER_25) -> Reports:
    return Reports(cast(ApiClient, api), now=lambda: now)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("2995.00", "2 995.00"),
        ("-349.5", "-349.50"),
        (Decimal("1234567.891"), "1 234 567.89"),
        ("0", "0.00"),
    ],
)
def test_amounts_have_two_decimals_and_spaced_thousands(value: Any, text: str) -> None:
    assert amount(value) == text


def test_money_and_months_read_naturally() -> None:
    assert money("5", "BYN") == "5.00 BYN"
    assert month_name(date(2026, 1, 1)) == "Январь 2026"
    assert month_name(date(2026, 12, 1)) == "Декабрь 2026"


async def test_the_balance_lists_accounts_and_the_total(api: FakeApi) -> None:
    reply = await reports(api).balance(ME)

    assert reply == Reply("Card: 2 995.00 BYN\nDollars: 200.00 USD\nИтого: 1 200.00 USD")


async def test_the_balance_without_accounts(api: FakeApi) -> None:
    api.answers["/accounts/balances"] = {"display_currency": "RUB", "total": "0", "accounts": []}

    assert await reports(api).balance(ME) == Reply("Счетов пока нет. Заведите первый в приложении.")


async def test_the_report_covers_this_month_in_the_household_time_zone(api: FakeApi) -> None:
    reply = await reports(api).report(ME)

    assert ("GET", "/reports", {"from": "2026-10-01", "to": "2026-10-31"}) in api.calls
    assert reply.text == "\n".join(
        [
            "Октябрь 2026, BYN",
            "Доходы: 2 995.00",
            "Расходы: 379.50",
            "Итог: 2 615.50",
            "",
            "Расходы:",
            "• Продукты — 329.50",
            "• Транспорт — 50.00",
            "",
            "Доходы:",
            "• Зарплата — 2 995.00",
            "",
            "План и факт:",
            "• Продукты: 329.50 из 400.00",
        ]
    )
    # This month: only the way back.
    assert reply.buttons == ((Button("← Сентябрь 2026", "rep:2026-09"),),)


async def test_a_previous_month_has_buttons_both_ways(api: FakeApi) -> None:
    reply = await reports(api).report(ME, "rep:2026-09")

    assert ("GET", "/reports", {"from": "2026-09-01", "to": "2026-09-30"}) in api.calls
    assert reply.buttons == (
        (Button("← Август 2026", "rep:2026-08"), Button("Октябрь 2026 →", "rep:2026-10")),
    )


async def test_months_roll_over_the_year(api: FakeApi) -> None:
    reply = await reports(api, datetime(2027, 3, 1, tzinfo=UTC)).report(ME, "rep:2026-12")

    assert [b.text for b in reply.buttons[0]] == ["← Ноябрь 2026", "Январь 2027 →"]


async def test_the_month_turns_at_midnight_in_minsk(api: FakeApi) -> None:
    # 22:00 UTC on 31 October is 01:00 on 1 November in Minsk.
    await reports(api, datetime(2026, 10, 31, 22, 0, tzinfo=UTC)).report(ME)

    assert ("GET", "/reports", {"from": "2026-11-01", "to": "2026-11-30"}) in api.calls


@pytest.mark.parametrize("data", ["rep:2026-13", "rep:", "rep"])
async def test_a_button_the_bot_did_not_send_shows_this_month(api: FakeApi, data: str) -> None:
    await reports(api).report(ME, data)

    assert ("GET", "/reports", {"from": "2026-10-01", "to": "2026-10-31"}) in api.calls


async def test_an_empty_month_says_so(api: FakeApi) -> None:
    api.answers["/reports"] = EMPTY_REPORT

    reply = await reports(api).report(ME)

    assert reply.text == "\n".join(
        [
            "Октябрь 2026, USD",
            "Доходы: 0.00",
            "Расходы: 0.00",
            "Итог: 0.00",
            "",
            "Операций за этот месяц нет.",
        ]
    )


async def test_the_currency_command_offers_the_three_currencies(api: FakeApi) -> None:
    reply = await reports(api).currency(ME)

    assert reply == Reply(
        "Суммы показываются в BYN. Выберите другую валюту:",
        ((Button("RUB", "cur:RUB"), Button("BYN", "cur:BYN"), Button("USD", "cur:USD")),),
    )


async def test_a_currency_button_changes_the_display_currency(api: FakeApi) -> None:
    reply = await reports(api).set_currency(ME, "cur:USD")

    assert api.calls == [("PATCH", "/me/settings", {"display_currency": "USD"})]
    assert reply == Reply("Готово: отчёты и балансы теперь в USD.")


async def test_an_unknown_currency_button_is_refused(api: FakeApi) -> None:
    assert (await reports(api).set_currency(ME, "cur:EUR")).text == messages.ENTRY_EXPIRED
    assert api.calls == []


@pytest.mark.parametrize("action", ["balance", "report", "currency", "set_currency"])
async def test_api_errors_are_explained(api: FakeApi, action: str) -> None:
    api.failure = ApiError(0, "api_unavailable", "")
    service = reports(api)
    calls = {
        "balance": lambda: service.balance(ME),
        "report": lambda: service.report(ME),
        "currency": lambda: service.currency(ME),
        "set_currency": lambda: service.set_currency(ME, "cur:USD"),
    }

    reply = await calls[action]()

    assert reply == Reply("Сервис сейчас недоступен. Попробуйте чуть позже.")
