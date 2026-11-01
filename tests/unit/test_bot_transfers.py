"""Transfers in the bot with a fake API client."""

from typing import Any, cast

import pytest

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError, Me
from family_pnl_bot.quick_entry import Button, Reply
from family_pnl_bot.transfers import TransferAccount, Transfers

ME = 1
CARD = TransferAccount("card", "Карта", "USD", "Карта · USD", own=True)
BOX = TransferAccount("box", "Копилка", "BYN", "Копилка · BYN · общий", own=True)


def account(account_id: str, currency: str, holder: str | None) -> dict[str, Any]:
    return {
        "id": account_id,
        "name": account_id.title(),
        "currency": currency,
        "shared": holder is None,
        "holder_id": holder,
    }


class FakeApi:
    def __init__(self) -> None:
        self.accounts = [account("card", "USD", "me"), account("box", "BYN", None)]
        self.members = [{"user_id": "me", "display_name": "Игорь", "email": None}]
        self.sent: list[Any] = []
        self.failure: ApiError | None = None

    async def me(self, telegram_id: int) -> Me:
        return Me(id="me", email=None, display_name=None, role="owner", household_name="F")

    async def request(self, telegram_id: int, method: str, path: str, **kw: Any) -> Any:
        if self.failure is not None:
            raise self.failure
        if path == "/accounts":
            return self.accounts
        if path == "/household/members":
            return self.members
        self.sent.append(kw["json"])
        amount = kw["json"]["amount"]
        converted = "324.50" if amount == "100.00" else amount
        return {
            "id": "op-1",
            "amount": amount,
            "currency": "USD",
            "target_amount": converted,
            "target_currency": "BYN" if converted != amount else "USD",
        }


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def transfers(api: FakeApi) -> Transfers:
    return Transfers(cast(ApiClient, api))


async def test_a_transfer_between_currencies_shows_both_amounts(api: FakeApi) -> None:
    reply = await transfers(api).transfer(ME, CARD, BOX, " 100 ")

    assert api.sent == [
        {"type": "transfer", "amount": "100.00", "account_id": "card", "target_account_id": "box"}
    ]
    assert reply == Reply(
        "Перевод 100.00 USD → 324.50 BYN: «Карта» → «Копилка».",
        ((Button("Отменить", "undo:op-1"),),),
    )


async def test_a_transfer_in_one_currency_shows_one_amount(api: FakeApi) -> None:
    reply = await transfers(api).transfer(ME, CARD, BOX, "50,5")

    assert reply is not None
    assert reply.text == "Перевод 50.50 USD: «Карта» → «Копилка»."


@pytest.mark.parametrize("text", ["много", "0", "-5", "1.005"])
async def test_not_an_amount_sends_nothing(api: FakeApi, text: str) -> None:
    assert await transfers(api).transfer(ME, CARD, BOX, text) is None
    assert api.sent == []


async def test_an_api_refusal_is_explained(api: FakeApi) -> None:
    api.failure = ApiError(503, "rates_unavailable", "")

    assert await transfers(api).transfer(ME, CARD, BOX, "100") == Reply(
        messages.ERRORS["rates_unavailable"]
    )
    assert await transfers(api).start(ME) == (Reply(messages.ERRORS["rates_unavailable"]), [])


async def test_other_members_accounts_are_targets_named_by_their_holder(api: FakeApi) -> None:
    api.accounts += [account("wallet", "BYN", "anna"), account("cash", "RUB", "ghost")]
    api.members += [{"user_id": "anna", "display_name": None, "email": "anna@example.com"}]

    reply, found = await transfers(api).start(ME)

    assert reply == Reply(messages.ASK_TRANSFER_SOURCE)
    assert [(a.label, a.own) for a in found] == [
        ("Card · USD", True),
        ("Box · BYN · общий", True),
        ("Wallet · BYN · anna@example.com", False),
        ("Cash · RUB · участник", False),
    ]


async def test_a_transfer_needs_an_own_account_and_two_accounts(api: FakeApi) -> None:
    api.accounts = [account("wallet", "BYN", "anna")]
    assert await transfers(api).start(ME) == (Reply(messages.NO_ACCOUNTS), [])

    api.accounts = [account("card", "USD", "me")]
    assert await transfers(api).start(ME) == (Reply(messages.TRANSFER_NEEDS_TWO), [])
