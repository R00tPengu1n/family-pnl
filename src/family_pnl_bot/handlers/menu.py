"""The menu buttons and the dialogs behind them (ADR-0011).

A menu button ends any dialog and does its action. A dialog asks one question at a time,
the answers on the keyboard in place of the menu; aiogram keeps its state, and the replies
come from the same functions the commands use. The result brings the menu back.
"""

from collections.abc import Awaitable, Callable
from typing import cast

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User

from family_pnl_bot import menu, messages
from family_pnl_bot.accounts import credentials_code, currency_code, open_account
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.budget import LIMIT_DATA, BudgetBot, limit_amount
from family_pnl_bot.keyboards import answer_markup, keyboard
from family_pnl_bot.quick_entry import Reply
from family_pnl_bot.replies import invite_replies, link_reply
from family_pnl_bot.reports import CURRENCY_PREFIX, INPUT_PREFIX, Reports
from family_pnl_bot.throttle import AttemptLimiter

MAX_ACCOUNT_NAME = 100  # the API's limit


class Dialog(StatesGroup):
    account_name = State()
    account_currency = State()
    account_kind = State()
    limit_category = State()
    limit_amount = State()
    currency = State()
    link_code = State()
    password = State()


def _sender(message: Message) -> int:
    # The router lets in only messages with a sender (channel posts have none).
    return cast(User, message.from_user).id


async def _ask(
    message: Message, state: FSMContext, step: State, text: str, rows: menu.Rows
) -> None:
    await state.set_state(step)
    await message.answer(text, reply_markup=keyboard(rows))


async def _finish(message: Message, state: FSMContext, reply: Reply) -> None:
    await state.clear()
    await message.answer(reply.text, reply_markup=answer_markup(reply))


# --- The menu ------------------------------------------------------------------------


async def on_menu(message: Message, state: FSMContext) -> None:
    await _finish(message, state, Reply(messages.MENU_SHOWN))


async def on_cancel(message: Message, state: FSMContext) -> None:
    await _finish(message, state, Reply(messages.CANCELLED))


async def on_help(message: Message, state: FSMContext) -> None:
    await _finish(message, state, Reply(messages.HELP))


async def on_record(message: Message, state: FSMContext) -> None:
    await _finish(message, state, Reply(messages.RECORD_HINT))


async def on_balance(message: Message, state: FSMContext, reports: Reports) -> None:
    await _finish(message, state, await reports.balance(_sender(message)))


async def on_report(message: Message, state: FSMContext, reports: Reports) -> None:
    await _finish(message, state, await reports.report(_sender(message)))


async def on_budget(message: Message, state: FSMContext, budget: BudgetBot) -> None:
    await _finish(message, state, await budget.view(_sender(message)))


async def on_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(messages.SETTINGS_TITLE, reply_markup=keyboard(menu.SETTINGS_MENU))


async def on_invite(message: Message, state: FSMContext, bot: Bot, api: ApiClient) -> None:
    await state.clear()
    me = await bot.me()
    for text in await invite_replies(api, _sender(message), me.username or ""):
        await message.answer(text, reply_markup=keyboard(menu.MAIN))


# --- New account: name, currency, and for the owner personal or shared ----------------


async def on_new_account(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ask(message, state, Dialog.account_name, messages.ASK_ACCOUNT_NAME, menu.ACCOUNT_NAME)


async def on_account_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 0 < len(name) <= MAX_ACCOUNT_NAME:
        await message.answer(messages.ACCOUNT_NAME_INVALID)
        return
    await state.update_data(name=name)
    await _ask(
        message, state, Dialog.account_currency, messages.ASK_ACCOUNT_CURRENCY, menu.CURRENCY
    )


async def on_account_currency(message: Message, state: FSMContext, api: ApiClient) -> None:
    currency = currency_code(message.text or "")
    if currency is None:
        await message.answer(messages.CHOOSE_CURRENCY_BUTTON)
        return
    try:
        me = await api.me(_sender(message))
    except ApiError as error:
        await _finish(message, state, Reply(messages.error_text(error)))
        return
    await state.update_data(currency=currency)
    if me.role == "owner":
        await _ask(
            message, state, Dialog.account_kind, messages.ASK_ACCOUNT_KIND, menu.ACCOUNT_KIND
        )
    else:
        await _open_account(message, state, api, shared=False)


async def on_account_kind(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text not in (menu.PERSONAL, menu.SHARED):
        await message.answer(messages.CHOOSE_ACCOUNT_KIND)
        return
    await _open_account(message, state, api, shared=message.text == menu.SHARED)


async def _open_account(
    message: Message, state: FSMContext, api: ApiClient, *, shared: bool
) -> None:
    data = await state.get_data()
    reply = await open_account(
        api, _sender(message), data["name"], data["currency"], shared, messages.account_opened
    )
    await _finish(message, state, reply)


# --- A limit: the button under the budget, then category and amount -------------------


async def on_limit_button(
    callback: CallbackQuery, state: FSMContext, bot: Bot, budget: BudgetBot
) -> None:
    await callback.answer()
    reply, categories = await budget.limit_categories(callback.from_user.id)
    if categories:
        await state.set_state(Dialog.limit_category)
        markup = keyboard(menu.choices(categories))
    else:
        await state.clear()
        markup = keyboard(menu.MAIN)
    # A private chat: its id is the member's.
    await bot.send_message(callback.from_user.id, reply.text, reply_markup=markup)


async def on_limit_category(message: Message, state: FSMContext) -> None:
    category = (message.text or "").strip()
    await state.update_data(category=category)
    await _ask(
        message,
        state,
        Dialog.limit_amount,
        messages.ask_limit_amount(category),
        menu.CANCEL_ONLY,
    )


async def on_limit_amount(message: Message, state: FSMContext, budget: BudgetBot) -> None:
    typed = (message.text or "").strip()
    if limit_amount(typed) is None:
        await message.answer(messages.LIMIT_AMOUNT_INVALID)
        return
    data = await state.get_data()
    reply = await budget.set_limit(_sender(message), f"{data['category']} {typed}")
    await _finish(message, state, reply)


# --- Settings: currencies, linking, email and password --------------------------------


async def on_display_currency(message: Message, state: FSMContext, reports: Reports) -> None:
    await _currency(message, state, reports, CURRENCY_PREFIX)


async def on_input_currency(message: Message, state: FSMContext, reports: Reports) -> None:
    await _currency(message, state, reports, INPUT_PREFIX)


async def _currency(message: Message, state: FSMContext, reports: Reports, prefix: str) -> None:
    reply = await reports.currency(_sender(message), prefix)
    if not reply.buttons:  # the API refused: nothing to choose
        await _finish(message, state, reply)
        return
    await state.set_data({"prefix": prefix})
    await _ask(message, state, Dialog.currency, reply.text, menu.CURRENCY)


async def on_currency(message: Message, state: FSMContext, reports: Reports) -> None:
    code = currency_code(message.text or "")
    if code is None:
        await message.answer(messages.CHOOSE_CURRENCY_BUTTON)
        return
    data = await state.get_data()
    await _finish(
        message, state, await reports.set_currency(_sender(message), f"{data['prefix']}:{code}")
    )


async def on_link_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ask(message, state, Dialog.link_code, messages.ASK_LINK_CODE, menu.CANCEL_ONLY)


async def on_link_code(
    message: Message, state: FSMContext, api: ApiClient, link_limiter: AttemptLimiter
) -> None:
    text = await link_reply(api, link_limiter, _sender(message), (message.text or "").strip())
    await _finish(message, state, Reply(text))


async def on_password_button(message: Message, state: FSMContext, docs_url: str | None) -> None:
    await state.clear()
    await _ask(
        message,
        state,
        Dialog.password,
        messages.credentials_intro(docs_url),
        menu.PASSWORD_CONFIRM,
    )


async def on_password_step(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text != menu.GET_CODE:
        await message.answer(messages.PRESS_GET_CODE)
        return
    await _finish(message, state, await credentials_code(api, _sender(message)))


def build_router() -> Router:
    router = Router(name="menu")
    router.message.filter(F.from_user)
    router.message.register(on_menu, Command("menu"))
    router.message.register(on_cancel, Command("cancel"))
    router.message.register(on_help, Command("help"))
    # Buttons first and in any state: a menu button always ends the dialog.
    buttons: dict[str, Callable[..., Awaitable[None]]] = {
        menu.CANCEL: on_cancel,
        menu.BACK: on_menu,
        menu.HELP: on_help,
        menu.RECORD: on_record,
        menu.BALANCE: on_balance,
        menu.REPORT: on_report,
        menu.BUDGET: on_budget,
        menu.SETTINGS: on_settings,
        menu.NEW_ACCOUNT: on_new_account,
        menu.DISPLAY_CURRENCY: on_display_currency,
        menu.INPUT_CURRENCY: on_input_currency,
        menu.INVITE: on_invite,
        menu.LINK: on_link_button,
        menu.CREDENTIALS: on_password_button,
    }
    for label, handler in buttons.items():
        router.message.register(handler, F.text == label)
    steps: dict[State, Callable[..., Awaitable[None]]] = {
        Dialog.account_name: on_account_name,
        Dialog.account_currency: on_account_currency,
        Dialog.account_kind: on_account_kind,
        Dialog.limit_category: on_limit_category,
        Dialog.limit_amount: on_limit_amount,
        Dialog.currency: on_currency,
        Dialog.link_code: on_link_code,
        Dialog.password: on_password_step,
    }
    for step, handler in steps.items():
        router.message.register(handler, StateFilter(step), F.text)
    router.callback_query.register(on_limit_button, F.data == LIMIT_DATA)
    return router
