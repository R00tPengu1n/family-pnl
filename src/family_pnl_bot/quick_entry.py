"""Quick entry: a message becomes an operation, with buttons where the bot cannot tell.

The currency defaults to the member's input currency. The category is matched by name,
ignoring case: an exact match first, then the only category the text starts. The
account: the member's (personal or shared) account in the entry's currency if there is
one, otherwise their only account; otherwise the member picks. A recorded entry can be
undone with a button. Nothing here imports aiogram: replies are text plus button data.
"""

import secrets
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.parser import Entry, EntryError, parse_entry

# Entries waiting for a button press; the oldest are forgotten first.
MAX_PENDING = 1000
MAX_OPTIONS = 20
CHOICE_PREFIX = "qe"
UNDO_PREFIX = "undo"


@dataclass(frozen=True, slots=True)
class Button:
    text: str
    data: str


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Option:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Pending:
    telegram_id: int
    entry: Entry
    currency: str
    category: Option | None  # None while the category is being asked
    options: tuple[Option, ...] = field(default=())  # what the buttons offer now


class QuickEntry:
    def __init__(self, api: ApiClient) -> None:
        self._api = api
        self._pending: OrderedDict[str, Pending] = OrderedDict()

    async def handle_text(self, telegram_id: int, text: str) -> Reply:
        try:
            entry = parse_entry(text)
        except EntryError as error:
            return Reply(str(error))
        try:
            return await self._resolve(telegram_id, entry)
        except ApiError as error:
            return Reply(messages.error_text(error))

    async def choose(self, telegram_id: int, data: str) -> Reply:
        """A button of a question: `qe:<pending id>:<index of the option>`."""
        parts = data.split(":")
        pending = self._pending.get(parts[1]) if len(parts) == 3 else None
        if pending is None or pending.telegram_id != telegram_id:
            return Reply(messages.ENTRY_EXPIRED)
        pending_id, index = parts[1], parts[2]
        if not index.isdigit() or int(index) >= len(pending.options):
            return Reply(messages.ENTRY_EXPIRED)  # not a button the bot sent
        del self._pending[pending_id]
        chosen = pending.options[int(index)]
        try:
            if pending.category is None:
                return await self._complete(pending, chosen)
            return await self._record(pending, pending.category, chosen)
        except ApiError as error:
            return Reply(messages.error_text(error))

    async def undo(self, telegram_id: int, data: str) -> Reply:
        """The undo button: `undo:<operation id>`."""
        operation_id = data.split(":", 1)[1]
        try:
            await self._api.request(telegram_id, "DELETE", f"/operations/{operation_id}")
        except ApiError as error:
            if error.code == "not_found":
                return Reply(messages.ENTRY_ALREADY_GONE)
            return Reply(messages.error_text(error))
        return Reply(messages.ENTRY_UNDONE)

    async def _resolve(self, telegram_id: int, entry: Entry) -> Reply:
        settings = await self._api.request(telegram_id, "GET", "/me/settings")
        kind = "income" if entry.income else "expense"
        categories = await self._api.request(
            telegram_id, "GET", "/categories", params={"kind": kind}
        )
        pending = Pending(
            telegram_id=telegram_id,
            entry=entry,
            currency=entry.currency or settings["input_currency"],
            category=None,
        )
        category, candidates = match_category(entry.category, categories)
        if category is None:
            return self._ask(pending, messages.CHOOSE_CATEGORY, candidates or categories)
        return await self._complete(pending, category)

    async def _complete(self, pending: Pending, category: Option) -> Reply:
        """The category is known: pick the account, or ask for it."""
        me = await self._api.me(pending.telegram_id)
        accounts = await self._api.request(pending.telegram_id, "GET", "/accounts")
        own = [a for a in accounts if a["shared"] or a["holder_id"] == me.id]
        if not own:
            return Reply(messages.NO_ACCOUNTS)
        account, candidates = _default_account(own, pending.currency)
        if account is None:
            return self._ask(
                replace(pending, category=category), messages.CHOOSE_ACCOUNT, candidates
            )
        return await self._record(pending, category, account)

    async def _record(self, pending: Pending, category: Option, account: Option) -> Reply:
        entry = pending.entry
        created = await self._api.request(
            pending.telegram_id,
            "POST",
            "/operations",
            json={
                "type": "income" if entry.income else "expense",
                "amount": str(entry.amount),
                "currency": pending.currency,
                "account_id": account.id,
                "category_id": category.id,
            },
        )
        text = messages.recorded(
            income=entry.income,
            amount=f"{entry.amount} {pending.currency}",
            category=category.name,
            account=account.name,
        )
        undo = Button(messages.UNDO_BUTTON, f"{UNDO_PREFIX}:{created['id']}")
        return Reply(text, ((undo,),))

    def _ask(self, pending: Pending, question: str, items: list[dict[str, Any]]) -> Reply:
        options = tuple(Option(item["id"], item["name"]) for item in items[:MAX_OPTIONS])
        pending_id = secrets.token_urlsafe(6)
        self._pending[pending_id] = replace(pending, options=options)
        while len(self._pending) > MAX_PENDING:
            self._pending.popitem(last=False)
        buttons = [
            Button(option.name, f"{CHOICE_PREFIX}:{pending_id}:{index}")
            for index, option in enumerate(options)
        ]
        rows = tuple(tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2))
        return Reply(question, rows)


def match_category(
    typed: str, categories: list[dict[str, Any]]
) -> tuple[Option | None, list[dict[str, Any]]]:
    """The category meant, or none and the candidates to offer."""
    key = typed.strip().casefold()
    for category in categories:
        if category["name"].casefold() == key:
            return Option(category["id"], category["name"]), []
    starting = [c for c in categories if c["name"].casefold().startswith(key)]
    if len(starting) == 1:
        return Option(starting[0]["id"], starting[0]["name"]), []
    return None, starting


def _default_account(
    accounts: list[dict[str, Any]], currency: str
) -> tuple[Option | None, list[dict[str, Any]]]:
    """The account to use, or none and the accounts to offer (those in the currency first)."""
    in_currency = [a for a in accounts if a["currency"] == currency]
    if len(in_currency) == 1:
        return Option(in_currency[0]["id"], in_currency[0]["name"]), []
    if len(accounts) == 1:
        return Option(accounts[0]["id"], accounts[0]["name"]), []
    others = [a for a in accounts if a["currency"] != currency]
    return None, in_currency + others
