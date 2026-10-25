"""/budget, /limit and approval: next month's draft and this month's execution.

Limits are set for next month's budget, the one prepared in the approval window. The
API decides who may change or approve it; the bot explains a refusal in Russian. Only
the owner gets the "Approve" button. Nothing here imports aiogram.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.formatting import amount, month_name, shift_month
from family_pnl_bot.quick_entry import Button, Reply, match_category

APPROVE_PREFIX = "bud"


def _now() -> datetime:
    return datetime.now(UTC)


class BudgetBot:
    def __init__(self, api: ApiClient, now: Callable[[], datetime] = _now) -> None:
        self._api = api
        self._now = now

    async def view(self, telegram_id: int) -> Reply:
        try:
            current = await self._this_month(telegram_id)
            following = shift_month(current, 1)
            me = await self._api.me(telegram_id)
            draft = await self._api.request(telegram_id, "GET", f"/budgets/{_key(following)}")
            execution = await self._api.request(
                telegram_id, "GET", f"/budgets/{_key(current)}/execution"
            )
        except ApiError as error:
            return Reply(messages.error_text(error))
        text = "\n".join(
            [*_draft_lines(following, draft), "", *_execution_lines(current, execution)]
        )
        if me.role != "owner" or draft["status"] == "approved":
            return Reply(text)
        approve = Button(messages.APPROVE_BUTTON, f"{APPROVE_PREFIX}:approve:{_key(following)}")
        return Reply(text, ((approve,),))

    async def set_limit(self, telegram_id: int, args: str | None) -> Reply:
        """`/limit продукты 800`: the limit of a category in next month's budget."""
        words = (args or "").split()
        limit = _limit_amount(words[-1]) if len(words) > 1 else None
        if limit is None:
            return Reply(messages.LIMIT_USAGE)
        try:
            following = shift_month(await self._this_month(telegram_id), 1)
            categories = await self._api.request(
                telegram_id, "GET", "/categories", params={"kind": "expense"}
            )
            category, _ = match_category(" ".join(words[:-1]), categories)
            if category is None:
                return Reply(messages.no_expense_category(" ".join(words[:-1])))
            budget = await self._api.request(
                telegram_id,
                "PUT",
                f"/budgets/{_key(following)}/limits/{category.id}",
                json={"amount": str(limit)},
            )
        except ApiError as error:
            if error.code == "permission_denied":
                return Reply(messages.LIMIT_REFUSED)
            return Reply(messages.error_text(error))
        return Reply(
            messages.limit_set(
                category.name, month_name(following), f"{amount(limit)} {budget['currency']}"
            )
        )

    async def approve(self, telegram_id: int, data: str) -> Reply:
        """The approve button: `bud:approve:YYYY-MM`."""
        month = data.rsplit(":", 1)[-1]
        try:
            await self._api.request(telegram_id, "POST", f"/budgets/{month}/approve")
        except ApiError as error:
            if error.code == "permission_denied":
                return Reply(messages.APPROVE_REFUSED)
            if error.code == "not_found":
                return Reply(messages.NOTHING_TO_APPROVE)
            return Reply(messages.error_text(error))
        return Reply(messages.approved(month_name(date.fromisoformat(f"{month}-01"))))

    async def _this_month(self, telegram_id: int) -> date:
        settings = await self._api.request(telegram_id, "GET", "/household/settings")
        return self._now().astimezone(ZoneInfo(settings["timezone"])).date().replace(day=1)


def _key(month: date) -> str:
    return month.strftime("%Y-%m")


def _limit_amount(word: str) -> Decimal | None:
    """A positive amount with at most two decimals, a comma allowed; None otherwise."""
    try:
        value = Decimal(word.replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal("0.01")):
        return None
    return value.quantize(Decimal("0.01"))


def _draft_lines(month: date, draft: dict[str, Any]) -> list[str]:
    window = draft["window"]
    if draft["status"] == "approved":
        status = "утверждён"
    elif window["missed"]:
        status = "не утверждён: окно закрылось"
    else:
        status = "черновик"
    opens = date.fromisoformat(window["opens"]).strftime("%d.%m")
    closes = date.fromisoformat(window["closes"]).strftime("%d.%m")
    lines = [
        f"Бюджет на {month_name(month).lower()}, {draft['currency']}: {status}",
        f"Окно утверждения: {opens}–{closes}" + (" (открыто)" if window["open"] else ""),
    ]
    if not draft["limits"]:
        return [*lines, "Лимитов пока нет. Задайте: /limit продукты 800"]
    return lines + [f"• {item['category']} — {amount(item['amount'])}" for item in draft["limits"]]


def _execution_lines(month: date, execution: dict[str, Any]) -> list[str]:
    title = f"{month_name(month)}, {execution['currency']}: потрачено из лимита"
    if not execution["categories"]:
        return [title, "Бюджета на этот месяц нет."]
    return [title] + [
        f"• {c['category']}: {amount(c['spent'])} из {amount(c['limit'])} ({c['percent']}%)"
        for c in execution["categories"]
    ]
