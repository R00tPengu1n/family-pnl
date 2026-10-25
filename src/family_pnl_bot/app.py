"""The bot process: long polling with aiogram, talking to the API over httpx."""

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType

from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.budget import BudgetBot
from family_pnl_bot.config import BotSettings
from family_pnl_bot.handlers import budget, quick_entry, reports, start
from family_pnl_bot.quick_entry import QuickEntry
from family_pnl_bot.reports import Reports
from family_pnl_bot.throttle import AttemptLimiter


def build_dispatcher(api: ApiClient, link_limiter: AttemptLimiter) -> Dispatcher:
    """Routers plus the objects handlers receive by name (`api`, `link_limiter`, ...)."""
    dispatcher = Dispatcher()
    # Private chats only: in a group every message would read as a quick entry, and the
    # buttons would show the family's categories to everyone there.
    dispatcher.message.filter(F.chat.type == ChatType.PRIVATE)
    # Commands first: quick entry takes every other text message.
    dispatcher.include_router(start.build_router())
    dispatcher.include_router(reports.build_router())
    dispatcher.include_router(budget.build_router())
    dispatcher.include_router(quick_entry.build_router())
    dispatcher["api"] = api
    dispatcher["link_limiter"] = link_limiter
    dispatcher["quick_entry"] = QuickEntry(api)
    dispatcher["reports"] = Reports(api)
    dispatcher["budget"] = BudgetBot(api)
    return dispatcher


async def main(settings: BotSettings | None = None) -> None:
    settings = settings or BotSettings()
    limiter = AttemptLimiter(settings.link_max_attempts, settings.link_window_seconds)
    async with httpx.AsyncClient(base_url=settings.api_url, timeout=10.0) as http:
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        dispatcher = build_dispatcher(ApiClient(http, settings.bot_api_secret), limiter)
        try:
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()
