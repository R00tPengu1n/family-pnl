"""/start registers or welcomes back, /start <invite> joins a household, /link links an account."""

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.replies import link_reply, start_reply
from family_pnl_bot.throttle import AttemptLimiter


async def on_start(message: Message, command: CommandObject, api: ApiClient) -> None:
    user = message.from_user
    if user is None:
        return  # channel posts have no sender
    await message.answer(await start_reply(api, user.id, user.first_name, command.args))


async def on_link(
    message: Message, command: CommandObject, api: ApiClient, link_limiter: AttemptLimiter
) -> None:
    user = message.from_user
    if user is None:
        return
    await message.answer(await link_reply(api, link_limiter, user.id, command.args))


def build_router() -> Router:
    """A router can join one dispatcher only, so each dispatcher gets a fresh one."""
    router = Router(name="start")
    router.message.register(on_start, CommandStart())
    router.message.register(on_link, Command("link"))
    return router
