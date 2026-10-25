"""Reply buttons as Telegram inline keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from family_pnl_bot.quick_entry import Reply


def markup(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button.text, callback_data=button.data) for button in row]
            for row in reply.buttons
        ]
    )
