"""The bot's API client talking to the real application in-process, and a fake Telegram.

aiogram builds hundreds of models when imported (about ten seconds under coverage), so the
`telegram` fixture imports it inside, and the tests that use it share one xdist worker
(`xdist_group("aiogram")`): the other workers never pay for the import.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.throttle import AttemptLimiter
from tests.integration.conftest import BOT_SECRET

ANNA, IVAN = 5000000001, 5000000002
TOKEN = "123456:test-token"
BOT_NAME = "FamilyPnLBot"


class CountingTransport(httpx.AsyncBaseTransport):
    """Forwards to the app and remembers the paths asked for."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


class Monotonic:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def transport(app: FastAPI) -> CountingTransport:
    return CountingTransport(httpx.ASGITransport(app=app, raise_app_exceptions=False))


@pytest.fixture
def monotonic() -> Monotonic:
    return Monotonic()


@pytest.fixture
async def api(transport: CountingTransport, monotonic: Monotonic) -> AsyncIterator[ApiClient]:
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield ApiClient(http, SecretStr(BOT_SECRET), now=monotonic)


@dataclass
class Telegram:
    """A dispatcher fed with updates; what the bot sent is recorded instead of posted."""

    feed: Callable[..., Awaitable[None]]
    press: Callable[[str, bool], Awaitable[None]]
    sent: list[str]
    buttons: list[list[str]]  # callback data of the inline buttons of the last message
    keyboard: list[list[str]]  # texts of the last reply keyboard: the menu or the answers
    dispatcher: Any


@pytest.fixture
def telegram(api: ApiClient) -> Telegram:
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import (
        AnswerCallbackQuery,
        EditMessageText,
        GetMe,
        SendMessage,
        SetMyCommands,
    )
    from aiogram.types import (
        CallbackQuery,
        Chat,
        InlineKeyboardMarkup,
        Message,
        ReplyKeyboardMarkup,
        Update,
        User,
    )

    from family_pnl_bot.app import build_dispatcher

    sent: list[str] = []
    buttons: list[list[str]] = []
    keyboard: list[list[str]] = []

    class RecordingSession(BaseSession):
        async def make_request(self, bot: Bot, method: Any, **_: Any) -> Any:
            if isinstance(method, AnswerCallbackQuery | SetMyCommands):
                return True
            if isinstance(method, GetMe):
                return User(id=1, is_bot=True, first_name="Бот", username=BOT_NAME)
            assert isinstance(method, SendMessage | EditMessageText)
            sent.append(method.text)
            markup = method.reply_markup
            inline = markup.inline_keyboard if isinstance(markup, InlineKeyboardMarkup) else []
            buttons[:] = [[button.callback_data for button in row] for row in inline]
            if isinstance(markup, ReplyKeyboardMarkup):
                keyboard[:] = [[button.text for button in row] for row in markup.keyboard]
            return Message(
                message_id=2,
                date=datetime.now(UTC),
                chat=Chat(id=ANNA, type="private"),
                text=method.text,
            )

        async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
            for chunk in ():  # the handlers download no files
                yield chunk

        async def close(self) -> None:
            return None

    bot = Bot(TOKEN, session=RecordingSession())
    dispatcher = build_dispatcher(api, AttemptLimiter(5, 900))

    async def feed(text: str, user_id: int | None = ANNA, chat: str = "private") -> None:
        sender = None if user_id is None else User(id=user_id, is_bot=False, first_name="Анна")
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user_id or -100, type=chat),
            from_user=sender,
            text=text,
        )
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    async def press(data: str, on_message: bool = True) -> None:
        # Telegram leaves out the message when it is too old for the bot to see.
        shown = Message(
            message_id=2, date=datetime.now(UTC), chat=Chat(id=ANNA, type="private"), text="?"
        )
        callback = CallbackQuery(
            id="1",
            from_user=User(id=ANNA, is_bot=False, first_name="Анна"),
            chat_instance="chat",
            data=data,
            message=shown if on_message else None,
        )
        await dispatcher.feed_update(bot, Update(update_id=2, callback_query=callback))

    return Telegram(feed, press, sent, buttons, keyboard, dispatcher)
