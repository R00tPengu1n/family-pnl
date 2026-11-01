"""Telegram markup: inline buttons of a reply, and reply keyboards for the menu and dialogs."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from family_pnl_bot import menu
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


def keyboard(rows: menu.Rows) -> ReplyKeyboardMarkup:
    """A keyboard under the input field; persistent, so it stays while the bot waits."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def answer_markup(reply: Reply) -> InlineKeyboardMarkup | ReplyKeyboardMarkup:
    """A new message: its inline buttons, or else the menu.

    A message carries one markup. One with inline buttons leaves the menu the chat already
    shows in place; every other reply brings the menu back.
    """
    return markup(reply) or keyboard(menu.MAIN)
