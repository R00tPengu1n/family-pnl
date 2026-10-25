"""/balance, /report, /currency, /input and /account: the member's money and settings."""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from family_pnl_bot.accounts import create_account
from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.keyboards import markup
from family_pnl_bot.quick_entry import Reply
from family_pnl_bot.reports import CURRENCY_PREFIX, INPUT_PREFIX, REPORT_PREFIX, Reports


async def on_balance(message: Message, reports: Reports) -> None:
    if message.from_user is not None:
        await _answer(message, await reports.balance(message.from_user.id))


async def on_report(message: Message, reports: Reports) -> None:
    if message.from_user is not None:
        await _answer(message, await reports.report(message.from_user.id))


async def on_currency(message: Message, reports: Reports) -> None:
    if message.from_user is not None:
        await _answer(message, await reports.currency(message.from_user.id))


async def on_input(message: Message, reports: Reports) -> None:
    if message.from_user is not None:
        await _answer(message, await reports.currency(message.from_user.id, INPUT_PREFIX))


async def on_account(message: Message, command: CommandObject, api: ApiClient) -> None:
    if message.from_user is not None:
        await _answer(message, await create_account(api, message.from_user.id, command.args))


async def on_report_month(callback: CallbackQuery, reports: Reports) -> None:
    await _edit(callback, await reports.report(callback.from_user.id, callback.data))


async def on_currency_choice(callback: CallbackQuery, reports: Reports) -> None:
    await _edit(callback, await reports.set_currency(callback.from_user.id, callback.data or ""))


async def _answer(message: Message, reply: Reply) -> None:
    await message.answer(reply.text, reply_markup=markup(reply))


async def _edit(callback: CallbackQuery, reply: Reply) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(reply.text, reply_markup=markup(reply))
    await callback.answer()


def build_router() -> Router:
    router = Router(name="reports")
    router.message.register(on_balance, Command("balance"))
    router.message.register(on_report, Command("report"))
    router.message.register(on_currency, Command("currency"))
    router.message.register(on_input, Command("input"))
    router.message.register(on_account, Command("account"))
    router.callback_query.register(on_report_month, F.data.startswith(f"{REPORT_PREFIX}:"))
    for prefix in (CURRENCY_PREFIX, INPUT_PREFIX):
        router.callback_query.register(on_currency_choice, F.data.startswith(f"{prefix}:"))
    return router
