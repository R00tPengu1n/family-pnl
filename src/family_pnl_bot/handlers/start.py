"""/start registers or welcomes back, /start <invite> joins a household, /link links an account."""

from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from family_pnl_bot import menu
from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.keyboards import keyboard
from family_pnl_bot.replies import link_reply, start_reply
from family_pnl_bot.throttle import AttemptLimiter


async def on_start(
    message: Message, command: CommandObject, state: FSMContext, api: ApiClient
) -> None:
    user = cast(User, message.from_user)  # the router lets in only messages with a sender
    await state.clear()
    text = await start_reply(api, user.id, user.first_name, command.args)
    await message.answer(text, reply_markup=keyboard(menu.MAIN))


async def on_link(
    message: Message, command: CommandObject, api: ApiClient, link_limiter: AttemptLimiter
) -> None:
    user = cast(User, message.from_user)
    text = await link_reply(api, link_limiter, user.id, command.args)
    await message.answer(text, reply_markup=keyboard(menu.MAIN))


def build_router() -> Router:
    """A router can join one dispatcher only, so each dispatcher gets a fresh one."""
    router = Router(name="start")
    router.message.filter(F.from_user)  # channel posts have no sender
    router.message.register(on_start, CommandStart())
    router.message.register(on_link, Command("link"))
    return router
