"""The aiogram side of the bot: commands routed to handlers, polling, `python -m`.

aiogram builds hundreds of models when imported (about ten seconds under coverage), so
this module imports it inside its fixtures and tests, and all its tests share one xdist
worker (`--dist loadgroup`): the other workers never pay for the import.
"""

import runpy
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient
from family_pnl_bot.throttle import AttemptLimiter

pytestmark = pytest.mark.xdist_group("aiogram")

ANNA = 5000000001
TOKEN = "123456:test-token"


@dataclass
class Telegram:
    """A dispatcher fed with updates; what the bot sent is recorded instead of posted."""

    feed: Callable[[str, int | None], Awaitable[None]]
    sent: list[str]
    dispatcher: Any


@pytest.fixture
def telegram(api: ApiClient) -> Telegram:
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import SendMessage
    from aiogram.types import Chat, Message, Update, User

    from family_pnl_bot.app import build_dispatcher

    sent: list[str] = []

    class RecordingSession(BaseSession):
        async def make_request(self, bot: Bot, method: Any, **_: Any) -> Any:
            assert isinstance(method, SendMessage)
            sent.append(method.text)
            return Message(
                message_id=2,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )

        async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
            for chunk in ():  # the handlers download no files
                yield chunk

        async def close(self) -> None:
            return None

    bot = Bot(TOKEN, session=RecordingSession())
    dispatcher = build_dispatcher(api, AttemptLimiter(5, 900))

    async def feed(text: str, user_id: int | None = ANNA) -> None:
        sender = None if user_id is None else User(id=user_id, is_bot=False, first_name="Анна")
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user_id or -100, type="private"),
            from_user=sender,
            text=text,
        )
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    return Telegram(feed, sent, dispatcher)


async def test_commands_reach_their_handlers_with_their_dependencies(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed("/link", ANNA)

    assert telegram.sent == [messages.created("Family"), messages.LINK_USAGE]
    assert (await api.me(ANNA)).display_name == "Анна"
    assert [router.name for router in telegram.dispatcher.sub_routers] == ["start"]


async def test_the_command_argument_reaches_the_reply(telegram: Telegram) -> None:
    await telegram.feed("/start NOPE-NOPE", ANNA)

    assert telegram.sent == [messages.ERRORS["invite_invalid"]]


async def test_messages_without_a_sender_get_no_answer(telegram: Telegram) -> None:
    await telegram.feed("/start", None)
    await telegram.feed("/link CODE", None)

    assert telegram.sent == []


async def test_main_polls_with_the_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiogram import Dispatcher
    from pydantic import SecretStr

    from family_pnl_bot.app import main
    from family_pnl_bot.config import BotSettings

    polled: list[str] = []

    async def fake_polling(self: Dispatcher, bot: Any) -> None:
        polled.append(bot.token)

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    settings = BotSettings(
        _env_file=None, telegram_bot_token=SecretStr(TOKEN), bot_api_secret=SecretStr("s" * 32)
    )

    await main(settings)

    assert polled == [TOKEN]


def test_running_the_package_starts_main(monkeypatch: pytest.MonkeyPatch) -> None:
    import family_pnl_bot.app

    started: list[bool] = []

    async def fake_main() -> None:
        started.append(True)

    monkeypatch.setattr(family_pnl_bot.app, "main", fake_main)

    runpy.run_module("family_pnl_bot", run_name="__main__")

    assert started == [True]
