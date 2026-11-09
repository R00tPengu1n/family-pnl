"""The aiogram side of the bot: commands routed to handlers, polling, `python -m`.

aiogram builds hundreds of models when imported (about ten seconds under coverage), so
this module imports it inside its fixtures and tests, and all its tests share one xdist
worker (`--dist loadgroup`): the other workers never pay for the import.
"""

import runpy
from typing import Any

import pytest

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient
from tests.integration.bot.conftest import ANNA, TOKEN, Telegram

pytestmark = pytest.mark.xdist_group("aiogram")


async def test_commands_reach_their_handlers_with_their_dependencies(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed("/link", ANNA)

    assert telegram.sent == [messages.created("Family"), messages.LINK_USAGE]
    assert (await api.me(ANNA)).display_name == "Анна"
    assert [router.name for router in telegram.dispatcher.sub_routers] == [
        "start",
        "menu",
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
        "/password",
        "/budget",
        "/limit x 1",
    ):
        await telegram.feed(command, None)

    assert telegram.sent == []


async def test_main_polls_with_the_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.types import BotCommand
    from pydantic import SecretStr

    from family_pnl_bot.app import main
    from family_pnl_bot.config import BotSettings

    polled: list[str] = []
    commands: list[list[str]] = []

    async def fake_polling(self: Dispatcher, bot: Any) -> None:
        polled.append(bot.token)
        assert self["docs_url"] == "https://pnl.example.com/docs"

    async def fake_set_commands(self: Bot, entries: list[BotCommand]) -> bool:
        commands.append([entry.command for entry in entries])
        return True

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    monkeypatch.setattr(Bot, "set_my_commands", fake_set_commands)
    settings = BotSettings(
        _env_file=None,
        telegram_bot_token=SecretStr(TOKEN),
        bot_api_secret=SecretStr("s" * 32),
        public_api_url="https://pnl.example.com/",
    )

    await main(settings)

    assert polled == [TOKEN]
    assert commands == [["menu", "cancel", "help", "start"]]


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
    assert balance.splitlines()[:3] == ["Card: 0.00 RUB", "Итого: 0.00 RUB", ""]
    assert balance.splitlines()[3].endswith(": расходы 0.00 RUB")
    assert balance.splitlines()[4] == messages.NO_LIMITS_THIS_MONTH
    assert currency == "Суммы показываются в RUB. Выберите другую валюту:"
    assert changed == "Готово: отчёты и балансы теперь в USD."
    assert report.splitlines()[0].endswith(", USD")
    assert previous.splitlines()[0].endswith(", USD")
    assert previous.splitlines()[0] != report.splitlines()[0]


async def test_budget_limit_and_approve_reach_their_handlers(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed("/limit продукты 800", ANNA)
    await telegram.feed("/budget", ANNA)
    [[_limit], [approve]] = telegram.buttons
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


async def test_password_hands_out_a_code_for_the_api(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed("/password", ANNA)

    assert telegram.sent[1].startswith("Ваш код: ")
