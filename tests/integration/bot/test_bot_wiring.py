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

    feed: Callable[..., Awaitable[None]]
    press: Callable[[str, bool], Awaitable[None]]
    sent: list[str]
    buttons: list[list[str]]  # callback data of the last keyboard the bot sent
    dispatcher: Any


@pytest.fixture
def telegram(api: ApiClient) -> Telegram:
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
    from aiogram.types import CallbackQuery, Chat, Message, Update, User

    from family_pnl_bot.app import build_dispatcher

    sent: list[str] = []
    buttons: list[list[str]] = []

    class RecordingSession(BaseSession):
        async def make_request(self, bot: Bot, method: Any, **_: Any) -> Any:
            if isinstance(method, AnswerCallbackQuery):
                return True
            assert isinstance(method, SendMessage | EditMessageText)
            sent.append(method.text)
            keyboard = method.reply_markup.inline_keyboard if method.reply_markup else []
            buttons[:] = [[button.callback_data for button in row] for row in keyboard]
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

    return Telegram(feed, press, sent, buttons, dispatcher)


async def test_commands_reach_their_handlers_with_their_dependencies(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed("/link", ANNA)

    assert telegram.sent == [messages.created("Family"), messages.LINK_USAGE]
    assert (await api.me(ANNA)).display_name == "Анна"
    assert [router.name for router in telegram.dispatcher.sub_routers] == [
        "start",
        "reports",
        "budget",
        "quick_entry",
    ]


async def test_the_command_argument_reaches_the_reply(telegram: Telegram) -> None:
    await telegram.feed("/start NOPE-NOPE", ANNA)

    assert telegram.sent == [messages.ERRORS["invite_invalid"]]


async def test_messages_without_a_sender_get_no_answer(telegram: Telegram) -> None:
    await telegram.feed("/start", None)
    await telegram.feed("/link CODE", None)
    await telegram.feed("кофе 5", None)
    for command in (
        "/balance",
        "/report",
        "/currency",
        "/input",
        "/account Карта BYN",
        "/budget",
        "/limit x 1",
    ):
        await telegram.feed(command, None)

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


async def card_for(api: ApiClient) -> None:
    await api.request(
        ANNA, "POST", "/accounts", json={"name": "Card", "type": "card", "currency": "RUB"}
    )


async def test_a_quick_entry_is_recorded_and_undone_with_its_button(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await card_for(api)

    await telegram.feed("продукты 5", ANNA)
    [[undo]] = telegram.buttons
    await telegram.press(undo)

    assert telegram.sent[1:] == [
        "Расход 5.00 RUB записан: «Продукты», счёт «Card».",
        "Запись отменена.",
    ]
    assert telegram.buttons == []
    assert (await api.request(ANNA, "GET", "/operations"))["items"] == []


async def test_a_category_chosen_with_a_button_records_the_entry(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await card_for(api)

    await telegram.feed("кофе 5", ANNA)
    first = telegram.buttons[0][0]
    await telegram.press(first)

    assert telegram.sent[1] == "Какая категория?"
    assert telegram.sent[2].startswith("Расход 5.00 RUB записан")
    assert len((await api.request(ANNA, "GET", "/operations"))["items"]) == 1


async def test_a_button_on_a_message_out_of_reach_still_acts(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await card_for(api)
    await telegram.feed("продукты 5", ANNA)
    [[undo]] = telegram.buttons

    await telegram.press(undo, False)

    assert len(telegram.sent) == 2  # nothing to edit, the press is only acknowledged
    assert (await api.request(ANNA, "GET", "/operations"))["items"] == []


async def test_balance_report_and_currency_commands_answer(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await card_for(api)

    await telegram.feed("/balance", ANNA)
    await telegram.feed("/currency", ANNA)
    await telegram.press("cur:USD")
    await telegram.feed("/report", ANNA)
    [[back]] = telegram.buttons
    await telegram.press(back)
    await telegram.press(back, False)

    balance, currency, changed, report, previous = telegram.sent[1:]
    assert balance.splitlines() == ["Card: 0.00 RUB", "Итого: 0.00 RUB"]
    assert currency == "Суммы показываются в RUB. Выберите другую валюту:"
    assert changed == "Готово: отчёты и балансы теперь в USD."
    assert report.splitlines()[0].endswith(", USD")
    assert previous.splitlines()[0].endswith(", USD")
    assert previous.splitlines()[0] != report.splitlines()[0]


async def test_budget_limit_and_approve_reach_their_handlers(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed("/limit продукты 800", ANNA)
    await telegram.feed("/budget", ANNA)
    [[approve]] = telegram.buttons
    await telegram.press(approve)
    await telegram.press(approve, False)

    assert telegram.sent[1].startswith("Лимит «Продукты» на ")
    assert telegram.sent[2].startswith("Бюджет на ")
    assert telegram.sent[3].endswith(" утверждён.")
    assert len(telegram.sent) == 4  # the second press had no message to edit


async def test_a_telegram_only_member_opens_an_account_and_records(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed("/account Карта RUB", ANNA)
    await telegram.feed("/input", ANNA)
    await telegram.press("inp:RUB")
    await telegram.feed("продукты 5", ANNA)

    assert telegram.sent[1:4] == [
        "Счёт «Карта» в RUB создан.",
        "Сумма без валюты записывается в RUB. Выберите другую валюту:",
        "Готово: сумма без валюты теперь в RUB.",
    ]
    assert telegram.sent[4] == "Расход 5.00 RUB записан: «Продукты», счёт «Карта»."


async def test_the_bot_stays_silent_in_groups(telegram: Telegram, api: ApiClient) -> None:
    await telegram.feed("/start", ANNA)
    await card_for(api)

    for chat in ("group", "supergroup"):
        await telegram.feed("буду через 10", ANNA, chat)
        await telegram.feed("/balance", ANNA, chat)

    assert len(telegram.sent) == 1  # only the private /start
    assert (await api.request(ANNA, "GET", "/operations"))["items"] == []
