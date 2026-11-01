"""The limit dialog's first question with a fake API client."""

from datetime import UTC, datetime
from typing import Any, cast

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.budget import BudgetBot
from family_pnl_bot.quick_entry import Reply


class NoCategoriesApi:
    async def request(self, telegram_id: int, method: str, path: str, **_: Any) -> Any:
        return {"timezone": "Europe/Minsk"} if path == "/household/settings" else []


async def test_without_expense_categories_there_is_nothing_to_ask() -> None:
    budget = BudgetBot(
        cast(ApiClient, NoCategoriesApi()), now=lambda: datetime(2026, 10, 25, tzinfo=UTC)
    )

    assert await budget.limit_categories(1) == (Reply(messages.NO_EXPENSE_CATEGORIES), [])
