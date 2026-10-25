"""/budget, /limit <category> <amount> and the owner's approve button."""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from family_pnl_bot.budget import APPROVE_PREFIX, BudgetBot
from family_pnl_bot.keyboards import markup


async def on_budget(message: Message, budget: BudgetBot) -> None:
    if message.from_user is not None:
        reply = await budget.view(message.from_user.id)
        await message.answer(reply.text, reply_markup=markup(reply))


async def on_limit(message: Message, command: CommandObject, budget: BudgetBot) -> None:
    if message.from_user is not None:
        reply = await budget.set_limit(message.from_user.id, command.args)
        await message.answer(reply.text)


async def on_approve(callback: CallbackQuery, budget: BudgetBot) -> None:
    reply = await budget.approve(callback.from_user.id, callback.data or "")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(reply.text)
    await callback.answer()


def build_router() -> Router:
    router = Router(name="budget")
    router.message.register(on_budget, Command("budget"))
    router.message.register(on_limit, Command("limit"))
    router.callback_query.register(on_approve, F.data.startswith(f"{APPROVE_PREFIX}:approve:"))
    return router
