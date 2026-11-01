"""Transfers between accounts from the bot.

The money leaves one of the member's accounts (personal or shared) and can arrive on any
account of the family, another member's card included. The amount is in the source
account's currency; between currencies the API converts it at the day's rate. Nothing
here imports aiogram: replies are text plus button data.
"""

from dataclasses import dataclass
from typing import Any

from family_pnl_bot import menu, messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.budget import limit_amount
from family_pnl_bot.formatting import money
from family_pnl_bot.quick_entry import UNDO_PREFIX, Button, Reply


@dataclass(frozen=True, slots=True)
class TransferAccount:
    id: str
    name: str
    currency: str
    label: str  # the button text
    own: bool  # the member may send money from it


class Transfers:
    def __init__(self, api: ApiClient) -> None:
        self._api = api

    async def start(self, telegram_id: int) -> tuple[Reply, list[TransferAccount]]:
        """The first question and the family's accounts; nothing to ask when it cannot be done."""
        try:
            me = await self._api.me(telegram_id)
            accounts = await self._api.request(telegram_id, "GET", "/accounts")
            members = await self._api.request(telegram_id, "GET", "/household/members")
        except ApiError as error:
            return Reply(messages.error_text(error)), []
        names = {m["user_id"]: m["display_name"] or m["email"] for m in members}
        found = [_account(a, me.id, names) for a in accounts]
        if not any(account.own for account in found):
            return Reply(messages.NO_ACCOUNTS), []
        if len(found) < 2:
            return Reply(messages.TRANSFER_NEEDS_TWO), []
        return Reply(messages.ASK_TRANSFER_SOURCE), found

    async def transfer(
        self, telegram_id: int, source: TransferAccount, target: TransferAccount, text: str
    ) -> Reply | None:
        """Send the amount; None when the text is not an amount."""
        amount = limit_amount(text.strip())
        if amount is None:
            return None
        try:
            created = await self._api.request(
                telegram_id,
                "POST",
                "/operations",
                json={
                    "type": "transfer",
                    "amount": str(amount),
                    "account_id": source.id,
                    "target_account_id": target.id,
                },
            )
        except ApiError as error:
            return Reply(messages.error_text(error))
        sent = money(created["amount"], created["currency"])
        received = money(created["target_amount"], created["target_currency"])
        text = messages.transferred(
            sent, received if received != sent else None, source.name, target.name
        )
        return Reply(text, ((Button(messages.UNDO_BUTTON, f"{UNDO_PREFIX}:{created['id']}"),),))


def _account(account: dict[str, Any], me: str, names: dict[str, str | None]) -> TransferAccount:
    own = account["shared"] or account["holder_id"] == me
    if own:
        label = menu.account_label(account)
    else:
        holder = names.get(account["holder_id"]) or messages.ANOTHER_MEMBER
        label = f"{account['name']} · {account['currency']} · {holder}"
    return TransferAccount(account["id"], account["name"], account["currency"], label, own)
