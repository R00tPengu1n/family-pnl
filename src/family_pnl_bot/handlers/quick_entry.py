"""Messages that are not commands are quick entries; their buttons come back as callbacks."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from family_pnl_bot.keyboards import markup
from family_pnl_bot.quick_entry import CHOICE_PREFIX, UNDO_PREFIX, QuickEntry, Reply


async def on_text(message: Message, quick_entry: QuickEntry) -> None:
    if message.from_user is None or message.text is None:
        return
    reply = await quick_entry.handle_text(message.from_user.id, message.text)
    await message.answer(reply.text, reply_markup=markup(reply))


async def on_choice(callback: CallbackQuery, quick_entry: QuickEntry) -> None:
    reply = await quick_entry.choose(callback.from_user.id, callback.data or "")
    await _show(callback, reply)


async def on_undo(callback: CallbackQuery, quick_entry: QuickEntry) -> None:
    reply = await quick_entry.undo(callback.from_user.id, callback.data or "")
    await _show(callback, reply)


async def _show(callback: CallbackQuery, reply: Reply) -> None:
    """Replace the question (or the confirmation) with the outcome."""
    if isinstance(callback.message, Message):
        await callback.message.edit_text(reply.text, reply_markup=markup(reply))
    await callback.answer()


def build_router() -> Router:
    router = Router(name="quick_entry")
    router.message.register(on_text, F.text, ~F.text.startswith("/"))
    router.callback_query.register(on_choice, F.data.startswith(f"{CHOICE_PREFIX}:"))
    router.callback_query.register(on_undo, F.data.startswith(f"{UNDO_PREFIX}:"))
    return router
