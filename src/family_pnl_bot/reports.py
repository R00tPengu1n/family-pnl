"""/balance, /report and /currency: what the member sees, in their display currency.

The API converts everything to the member's display currency; the bot only formats it.
The current month is the month of today in the household time zone. Nothing here
imports aiogram: replies are text plus button data.
"""

import calendar
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.formatting import amount, money, month_name, shift_month
from family_pnl_bot.quick_entry import Button, Reply

REPORT_PREFIX = "rep"
CURRENCY_PREFIX = "cur"
CURRENCIES = ("RUB", "BYN", "USD")


def _now() -> datetime:
    return datetime.now(UTC)


class Reports:
    def __init__(self, api: ApiClient, now: Callable[[], datetime] = _now) -> None:
        self._api = api
        self._now = now

    async def balance(self, telegram_id: int) -> Reply:
        try:
            body = await self._api.request(telegram_id, "GET", "/accounts/balances")
        except ApiError as error:
            return Reply(messages.error_text(error))
        if not body["accounts"]:
            return Reply(messages.NO_ACCOUNTS_YET)
        lines = [f"{a['name']}: {money(a['balance'], a['currency'])}" for a in body["accounts"]]
        lines.append(f"Итого: {money(body['total'], body['display_currency'])}")
        return Reply("\n".join(lines))

    async def report(self, telegram_id: int, data: str | None = None) -> Reply:
        """This month's report, or the month of a button: `rep:YYYY-MM`."""
        try:
            settings = await self._api.request(telegram_id, "GET", "/household/settings")
            today = self._now().astimezone(ZoneInfo(settings["timezone"])).date()
            current = today.replace(day=1)
            month = _month_of(data) or current
            last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
            body = await self._api.request(
                telegram_id,
                "GET",
                "/reports",
                params={"from": month.isoformat(), "to": last.isoformat()},
            )
        except ApiError as error:
            return Reply(messages.error_text(error))
        previous = shift_month(month, -1)
        buttons = [Button(f"← {month_name(previous)}", _report_data(previous))]
        if month < current:
            following = shift_month(month, 1)
            buttons.append(Button(f"{month_name(following)} →", _report_data(following)))
        return Reply(_report_text(month, body), (tuple(buttons),))

    async def currency(self, telegram_id: int) -> Reply:
        try:
            settings = await self._api.request(telegram_id, "GET", "/me/settings")
        except ApiError as error:
            return Reply(messages.error_text(error))
        row = tuple(Button(code, f"{CURRENCY_PREFIX}:{code}") for code in CURRENCIES)
        return Reply(messages.display_currency(settings["display_currency"]), (row,))

    async def set_currency(self, telegram_id: int, data: str) -> Reply:
        """A currency button: `cur:USD`."""
        code = data.split(":", 1)[1]
        if code not in CURRENCIES:
            return Reply(messages.ENTRY_EXPIRED)  # not a button the bot sent
        try:
            await self._api.request(
                telegram_id, "PATCH", "/me/settings", json={"display_currency": code}
            )
        except ApiError as error:
            return Reply(messages.error_text(error))
        return Reply(messages.currency_changed(code))


def _report_text(month: date, body: dict[str, Any]) -> str:
    totals = body["totals"]
    lines = [
        f"{month_name(month)}, {body['currency']}",
        f"Доходы: {amount(totals['income'])}",
        f"Расходы: {amount(totals['expense'])}",
        f"Итог: {amount(totals['net'])}",
    ]
    for kind, title in (("expense", "Расходы"), ("income", "Доходы")):
        found = [c for c in body["by_category"] if c["kind"] == kind]
        if found:
            lines += ["", f"{title}:"] + [
                f"• {c['category']} — {amount(c['amount'])}" for c in found
            ]
    if body["plan_vs_actual"]:
        lines += ["", "План и факт:"] + [
            f"• {p['category']}: {amount(p['actual'])} из {amount(p['planned'])}"
            for p in body["plan_vs_actual"]
        ]
    if not body["by_category"]:
        lines += ["", "Операций за этот месяц нет."]
    return "\n".join(lines)


def _month_of(data: str | None) -> date | None:
    """The month of a report button, or None for anything the bot did not send."""
    if data is None:
        return None
    try:
        return date.fromisoformat(data.split(":", 1)[1] + "-01")
    except (IndexError, ValueError):
        return None


def _report_data(month: date) -> str:
    return f"{REPORT_PREFIX}:{month.strftime('%Y-%m')}"
