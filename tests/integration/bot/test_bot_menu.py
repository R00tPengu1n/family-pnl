"""The menu buttons and the dialogs behind them, through aiogram, against the real API."""

import pytest

from family_pnl_bot import menu, messages
from family_pnl_bot.api_client import ApiClient
from tests.integration.bot.conftest import ANNA, BOT_NAME, IVAN, Telegram

pytestmark = pytest.mark.xdist_group("aiogram")

MAIN = [list(row) for row in menu.MAIN]
STRANGER = 5000000009  # never pressed /start


async def family(telegram: Telegram) -> None:
    """Anna owns the household; Ivan joins it through the invite link."""
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.INVITE, ANNA)
    code = telegram.sent[-1].rsplit("?start=", 1)[1]
    await telegram.feed(f"/start {code}", IVAN)


async def test_start_shows_the_menu_and_plain_replies_keep_it(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)
    assert telegram.keyboard == MAIN

    await telegram.feed(menu.SETTINGS, ANNA)
    assert telegram.sent[-1] == messages.SETTINGS_TITLE
    assert telegram.keyboard == [list(row) for row in menu.SETTINGS_MENU]

    await telegram.feed(menu.BACK, ANNA)
    assert (telegram.sent[-1], telegram.keyboard) == (messages.MENU_SHOWN, MAIN)


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        (menu.RECORD, messages.RECORD_HINT),
        (menu.HELP, messages.HELP),
        ("/help", messages.HELP),
        ("/menu", messages.MENU_SHOWN),
        ("/cancel", messages.CANCELLED),
        (menu.BALANCE, messages.NO_ACCOUNTS_YET),
    ],
)
async def test_a_menu_button_answers_with_the_menu(
    telegram: Telegram, text: str, reply: str
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.SETTINGS, ANNA)

    await telegram.feed(text, ANNA)

    assert (telegram.sent[-1], telegram.keyboard) == (reply, MAIN)


async def test_report_and_budget_come_with_their_inline_buttons(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed(menu.REPORT, ANNA)
    assert len(telegram.buttons) == 1  # the previous month

    await telegram.feed(menu.BUDGET, ANNA)
    assert telegram.sent[-1].startswith("Бюджет на ")
    assert telegram.buttons[0] == ["bud:limit"]


async def test_the_owner_opens_a_shared_account_step_by_step(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed(menu.NEW_ACCOUNT, ANNA)
    assert (telegram.sent[-1], telegram.keyboard) == (
        messages.ASK_ACCOUNT_NAME,
        [["Карта", "Наличные"], ["Отмена"]],
    )
    for wrong in ("   ", "x" * 101):
        await telegram.feed(wrong, ANNA)
        assert telegram.sent[-1] == messages.ACCOUNT_NAME_INVALID
    await telegram.feed("Копилка", ANNA)
    assert (telegram.sent[-1], telegram.keyboard) == (
        messages.ASK_ACCOUNT_CURRENCY,
        [["BYN", "RUB", "USD"], ["Отмена"]],
    )
    await telegram.feed("евро", ANNA)
    assert telegram.sent[-1] == messages.CHOOSE_CURRENCY_BUTTON
    await telegram.feed("BYN", ANNA)
    assert telegram.sent[-1] == messages.ASK_ACCOUNT_KIND
    assert telegram.keyboard == [["Личный", "Общий"], ["Отмена"]]
    await telegram.feed("не знаю", ANNA)
    assert telegram.sent[-1] == messages.CHOOSE_ACCOUNT_KIND
    await telegram.feed(menu.SHARED, ANNA)

    assert telegram.sent[-1] == (
        "Общий счёт «Копилка» в BYN создан.\n"
        "Записывайте траты одним сообщением: «кофе 5.50», «такси 300 rub», "
        "«+зарплата 2500 byn»."
    )
    assert telegram.keyboard == MAIN
    [account] = await api.request(ANNA, "GET", "/accounts")
    assert (account["name"], account["currency"], account["shared"]) == ("Копилка", "BYN", True)


async def test_a_member_is_not_asked_about_a_shared_account(
    telegram: Telegram, api: ApiClient
) -> None:
    await family(telegram)

    await telegram.feed(menu.NEW_ACCOUNT, IVAN)
    await telegram.feed("Карта", IVAN)
    await telegram.feed("usd", IVAN)

    assert telegram.sent[-1].startswith("Счёт «Карта» в USD создан.")
    [account] = await api.request(IVAN, "GET", "/accounts")
    assert account["shared"] is False


async def test_a_dialog_of_a_stranger_ends_with_the_api_refusal(telegram: Telegram) -> None:
    await telegram.feed(menu.NEW_ACCOUNT, STRANGER)
    await telegram.feed("Карта", STRANGER)
    await telegram.feed("BYN", STRANGER)

    assert telegram.sent[-1] == messages.ERRORS["telegram_not_registered"]
    assert telegram.keyboard == MAIN


async def test_cancel_ends_the_dialog(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.NEW_ACCOUNT, ANNA)

    await telegram.feed(menu.CANCEL, ANNA)
    await telegram.feed("продукты 5", ANNA)  # a quick entry again, not an account name

    assert telegram.sent[-2:] == [messages.CANCELLED, messages.NO_ACCOUNTS]


async def test_a_menu_button_ends_the_dialog_and_does_its_action(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.NEW_ACCOUNT, ANNA)

    await telegram.feed(menu.BALANCE, ANNA)
    await telegram.feed("продукты 5", ANNA)

    assert telegram.sent[-2:] == [messages.NO_ACCOUNTS_YET, messages.NO_ACCOUNTS]


async def test_a_limit_is_set_from_the_button_under_the_budget(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.BUDGET, ANNA)

    await telegram.press("bud:limit")
    assert telegram.sent[-1].startswith("Для какой категории задать лимит на ")
    assert any("Продукты" in row for row in telegram.keyboard)
    assert telegram.keyboard[-1] == ["Отмена"]
    await telegram.feed("Продукты", ANNA)
    assert (telegram.sent[-1], telegram.keyboard) == (
        messages.ask_limit_amount("Продукты"),
        [["Отмена"]],
    )
    await telegram.feed("много", ANNA)
    assert telegram.sent[-1] == messages.LIMIT_AMOUNT_INVALID
    await telegram.feed("800", ANNA)

    assert telegram.sent[-1].startswith("Лимит «Продукты» на ")
    assert telegram.keyboard == MAIN


async def test_the_limit_button_of_a_stranger_explains_and_keeps_the_menu(
    telegram: Telegram,
) -> None:
    await telegram.press("bud:limit")

    assert telegram.sent == [messages.ERRORS["telegram_not_registered"]]
    assert telegram.keyboard == MAIN


@pytest.mark.parametrize(
    ("button", "code", "done"),
    [
        (menu.DISPLAY_CURRENCY, "usd", "Готово: отчёты и балансы теперь в USD."),
        (menu.INPUT_CURRENCY, "BYN", "Готово: сумма без валюты теперь в BYN."),
    ],
)
async def test_a_currency_is_chosen_on_the_keyboard(
    telegram: Telegram, button: str, code: str, done: str
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.SETTINGS, ANNA)

    await telegram.feed(button, ANNA)
    assert telegram.keyboard == [["BYN", "RUB", "USD"], ["Отмена"]]
    await telegram.feed("евро", ANNA)
    assert telegram.sent[-1] == messages.CHOOSE_CURRENCY_BUTTON
    await telegram.feed(code, ANNA)

    assert (telegram.sent[-1], telegram.keyboard) == (done, MAIN)


async def test_a_currency_of_a_stranger_asks_nothing(telegram: Telegram) -> None:
    await telegram.feed(menu.DISPLAY_CURRENCY, STRANGER)
    await telegram.feed("USD", STRANGER)

    assert telegram.sent[0] == messages.ERRORS["telegram_not_registered"]
    assert telegram.keyboard == MAIN


async def test_the_owner_invites_with_a_link_and_a_member_cannot(telegram: Telegram) -> None:
    await family(telegram)
    invite_sent = telegram.sent[1:3]

    await telegram.feed(menu.INVITE, IVAN)
    await telegram.feed(menu.INVITE, STRANGER)

    assert invite_sent[0] == messages.INVITE_HOWTO
    assert invite_sent[1].startswith(
        f"Присоединяйся к нашему семейному бюджету: https://t.me/{BOT_NAME}?start="
    )
    assert telegram.sent[3].startswith("Готово, вы в семье «Family»!")
    assert telegram.sent[-2:] == [
        messages.INVITE_REFUSED,
        messages.ERRORS["telegram_not_registered"],
    ]


async def test_linking_asks_for_the_code(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed(menu.LINK, ANNA)
    assert (telegram.sent[-1], telegram.keyboard) == (messages.ASK_LINK_CODE, [["Отмена"]])
    await telegram.feed("AAAA-AAAA", ANNA)

    assert telegram.sent[-1] == messages.ERRORS["link_code_invalid"]
    assert telegram.keyboard == MAIN


async def test_email_and_password_are_explained_before_the_code(telegram: Telegram) -> None:
    await telegram.feed("/start", ANNA)

    await telegram.feed(menu.CREDENTIALS, ANNA)
    assert telegram.sent[-1] == messages.credentials_intro(None)
    assert telegram.keyboard == [["Получить код"], ["Отмена"]]
    await telegram.feed("мой пароль", ANNA)
    assert telegram.sent[-1] == messages.PRESS_GET_CODE
    await telegram.feed(menu.GET_CODE, ANNA)

    assert telegram.sent[-1].startswith("Ваш код: ")
    assert telegram.keyboard == MAIN


async def test_menu_messages_without_a_sender_get_no_answer(telegram: Telegram) -> None:
    await telegram.feed("/menu", None)
    await telegram.feed(menu.BALANCE, None)

    assert telegram.sent == []


def test_the_intro_links_the_api_documentation_when_known() -> None:
    intro = messages.credentials_intro("https://pnl.example.com/docs")

    assert "Откройте документацию API (https://pnl.example.com/docs)" in intro
    assert "Для бота пароль не нужен" in intro
    assert "Пароль в этот чат не пишите" in intro


def test_choices_put_options_in_rows_and_cancel_last() -> None:
    assert menu.choices(["a", "b", "c"]) == (("a", "b"), ("c",), ("Отмена",))


async def test_a_command_inside_a_dialog_is_not_taken_as_the_answer(
    telegram: Telegram, api: ApiClient
) -> None:
    await telegram.feed("/start", ANNA)
    await telegram.feed(menu.NEW_ACCOUNT, ANNA)

    await telegram.feed("/balance", ANNA)

    assert telegram.sent[-1] == messages.NO_ACCOUNTS_YET
    assert await api.request(ANNA, "GET", "/accounts") == []
