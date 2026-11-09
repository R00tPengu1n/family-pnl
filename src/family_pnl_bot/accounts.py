"""Opening an account from the bot: `/account <name> <currency> [общий]` or the dialog.

Telegram-only members have no password for the API, so the bot is their way to open the
accounts they record operations on. A personal account belongs to the member; a shared
one (owner only, the API decides) to the household. The type is a card; it can be
changed through the API.
"""

from collections.abc import Callable

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.parser import CURRENCY_ALIASES
from family_pnl_bot.quick_entry import Reply

SHARED_WORDS = ("общий", "общая", "shared")
_CURRENCY = {alias: code for code, aliases in CURRENCY_ALIASES.items() for alias in aliases}


async def create_account(api: ApiClient, telegram_id: int, args: str | None) -> Reply:
    words = (args or "").split()
    shared = bool(words) and words[-1].lower() in SHARED_WORDS
    if shared:
        words.pop()
    currency = _CURRENCY.get(words[-1].lower()) if len(words) > 1 else None
    if currency is None:
        return Reply(messages.ACCOUNT_USAGE)
    return await open_account(api, telegram_id, " ".join(words[:-1]), currency, shared)


def currency_code(word: str) -> str | None:
    """The ISO code of a currency word or sign (`byn`, `руб`, `$`), or None."""
    return _CURRENCY.get(word.strip().lower())


async def open_account(
    api: ApiClient,
    telegram_id: int,
    name: str,
    currency: str,
    shared: bool,
    done: Callable[[str, str, bool], str] = messages.account_created,
) -> Reply:
    """Open the account; `done` words the success (the dialog adds the next step)."""
    try:
        await api.request(
            telegram_id,
            "POST",
            "/accounts",
            json={"name": name, "type": "card", "currency": currency, "shared": shared},
        )
    except ApiError as error:
        if error.code == "permission_denied":
            return Reply(messages.SHARED_ACCOUNT_REFUSED)
        return Reply(messages.error_text(error))
    return Reply(done(name, currency, shared))


async def credentials_code(api: ApiClient, telegram_id: int) -> Reply:
    """/password: a code to set an email and password in the API; the bot never asks for one."""
    try:
        code = await api.credentials_code(telegram_id)
    except ApiError as error:
        return Reply(messages.error_text(error))
    return Reply(messages.credentials_code(code))
