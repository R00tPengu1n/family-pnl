"""The bot process: long polling with aiogram, talking to the API over httpx."""

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import BotCommand

from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.budget import BudgetBot
from family_pnl_bot.config import BotSettings
from family_pnl_bot.handlers import budget, menu, quick_entry, reports, start
from family_pnl_bot.quick_entry import QuickEntry
from family_pnl_bot.reports import Reports
from family_pnl_bot.throttle import AttemptLimiter
from family_pnl_bot.transfers import Transfers

# The "/" list in Telegram; everything else is on the menu buttons.
COMMANDS = (
    BotCommand(command="menu", description="Показать меню"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="start", description="Начать заново"),
)


def build_dispatcher(
    api: ApiClient, link_limiter: AttemptLimiter, docs_url: str | None = None
) -> Dispatcher:
    """Routers plus the objects handlers receive by name (`api`, `link_limiter`, ...)."""
    dispatcher = Dispatcher()
    # Private chats only: in a group every message would read as a quick entry, and the
    # buttons would show the family's categories to everyone there.
    dispatcher.message.filter(F.chat.type == ChatType.PRIVATE)
    # Commands and menu buttons first: quick entry takes every other text message.
    dispatcher.include_router(start.build_router())
    dispatcher.include_router(menu.build_router())
    dispatcher.include_router(reports.build_router())
    dispatcher.include_router(budget.build_router())
    dispatcher.include_router(quick_entry.build_router())
    dispatcher["api"] = api
    dispatcher["link_limiter"] = link_limiter
    dispatcher["docs_url"] = docs_url
    dispatcher["quick_entry"] = QuickEntry(api)
    dispatcher["reports"] = Reports(api)
    dispatcher["budget"] = BudgetBot(api)
    dispatcher["transfers"] = Transfers(api)
    return dispatcher


async def main(settings: BotSettings | None = None) -> None:
    settings = settings or BotSettings()
    limiter = AttemptLimiter(settings.link_max_attempts, settings.link_window_seconds)
    public = settings.public_api_url
    docs_url = f"{public.rstrip('/')}/docs" if public else None
    async with httpx.AsyncClient(base_url=settings.api_url, timeout=10.0) as http:
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        dispatcher = build_dispatcher(ApiClient(http, settings.bot_api_secret), limiter, docs_url)
        try:
            await bot.set_my_commands(list(COMMANDS))
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()
