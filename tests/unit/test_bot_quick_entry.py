"""Quick entry with a fake API client: matching, buttons, recording and undo."""

from typing import Any, cast

import pytest

from family_pnl_bot import messages, quick_entry
from family_pnl_bot.api_client import ApiClient, ApiError, Me
from family_pnl_bot.quick_entry import Button, QuickEntry, Reply

ME, OTHER = 1, 2
FOOD = {"id": "food", "name": "Продукты"}
TAXI = {"id": "taxi", "name": "Такси"}
TRANSPORT = {"id": "transport", "name": "Транспорт"}
SALARY = {"id": "salary", "name": "Зарплата"}


def account(account_id: str, currency: str, *, holder: str | None = "me") -> dict[str, Any]:
    return {
        "id": account_id,
        "name": account_id.title(),
        "currency": currency,
        "shared": holder is None,
        "holder_id": holder,
    }


class FakeApi:
    def __init__(self) -> None:
        self.input_currency = "BYN"
        self.categories = {"expense": [FOOD, TAXI, TRANSPORT], "income": [SALARY]}
        self.accounts = [account("card", "BYN")]
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.failures: dict[tuple[str, str], ApiError] = {}

    async def me(self, telegram_id: int) -> Me:
        return Me(id="me", email=None, display_name=None, role="member", household_name="F")

    async def request(
        self,
        telegram_id: int,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        if (method, path) in self.failures:
            raise self.failures[(method, path)]
        if path == "/me/settings":
            return {"input_currency": self.input_currency}
        if path == "/categories":
            assert params is not None
            return self.categories[params["kind"]]
        if path == "/accounts":
            return self.accounts
        if method == "POST":
            self.created.append(json)
            return {"id": f"00000000-0000-0000-0000-{len(self.created):012d}"}
        self.deleted.append(path)
        return None


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def entry(api: FakeApi) -> QuickEntry:
    return QuickEntry(cast(ApiClient, api))


def labels(reply: Reply) -> list[list[str]]:
    return [[button.text for button in row] for row in reply.buttons]


def data_of(reply: Reply, text: str) -> str:
    return next(b.data for row in reply.buttons for b in row if b.text == text)


async def test_an_exact_category_and_the_only_account_record_in_one_message(
    entry: QuickEntry, api: FakeApi
) -> None:
    reply = await entry.handle_text(ME, "продукты 12,5")

    assert api.created == [
        {
            "type": "expense",
            "amount": "12.50",
            "currency": "BYN",
            "account_id": "card",
            "category_id": "food",
        }
    ]
    assert reply == Reply(
        "Расход 12.50 BYN записан: «Продукты», счёт «Card».",
        ((Button("Отменить", "undo:00000000-0000-0000-0000-000000000001"),),),
    )


async def test_an_income_uses_income_categories(entry: QuickEntry, api: FakeApi) -> None:
    reply = await entry.handle_text(ME, "+зарплата 2500 usd")

    assert (api.created[0]["type"], api.created[0]["currency"]) == ("income", "USD")
    assert reply.text == "Доход 2500.00 USD записан: «Зарплата», счёт «Card»."


async def test_the_only_category_the_text_starts_is_taken(entry: QuickEntry, api: FakeApi) -> None:
    await entry.handle_text(ME, "прод 5")

    assert api.created[0]["category_id"] == "food"


async def test_the_account_in_the_entry_currency_is_taken(entry: QuickEntry, api: FakeApi) -> None:
    api.accounts = [account("card", "BYN"), account("rubles", "RUB")]

    await entry.handle_text(ME, "такси 300 rub")

    assert (api.created[0]["account_id"], api.created[0]["currency"]) == ("rubles", "RUB")


async def test_shared_accounts_count_and_other_members_accounts_do_not(
    entry: QuickEntry, api: FakeApi
) -> None:
    api.accounts = [account("ivans", "BYN", holder="ivan"), account("family", "BYN", holder=None)]

    await entry.handle_text(ME, "такси 5")

    assert api.created[0]["account_id"] == "family"


async def test_without_an_account_of_the_member_nothing_is_recorded(
    entry: QuickEntry, api: FakeApi
) -> None:
    api.accounts = [account("ivans", "BYN", holder="ivan")]

    reply = await entry.handle_text(ME, "такси 5")

    assert reply == Reply("Сначала заведите счёт: /account Карта BYN")
    assert api.created == []


async def test_no_match_offers_every_category_and_a_choice_records(
    entry: QuickEntry, api: FakeApi
) -> None:
    question = await entry.handle_text(ME, "кофе 5")

    assert question.text == "Какая категория?"
    assert labels(question) == [["Продукты", "Такси"], ["Транспорт"]]
    reply = await entry.choose(ME, data_of(question, "Такси"))

    assert api.created[0]["category_id"] == "taxi"
    assert reply.text == "Расход 5.00 BYN записан: «Такси», счёт «Card»."


async def test_an_ambiguous_start_offers_only_the_categories_it_starts(
    entry: QuickEntry,
) -> None:
    question = await entry.handle_text(ME, "т 5")

    assert labels(question) == [["Такси", "Транспорт"]]


async def test_several_accounts_are_offered_those_in_the_currency_first(
    entry: QuickEntry, api: FakeApi
) -> None:
    api.accounts = [account("dollars", "USD"), account("card", "BYN"), account("cash", "BYN")]

    question = await entry.handle_text(ME, "такси 5")
    assert (question.text, labels(question)) == ("С какого счёта?", [["Card", "Cash"], ["Dollars"]])
    await entry.choose(ME, data_of(question, "Cash"))

    assert api.created[0]["account_id"] == "cash"


async def test_one_account_not_in_the_currency_is_still_the_default(
    entry: QuickEntry, api: FakeApi
) -> None:
    api.accounts = [account("dollars", "USD")]

    await entry.handle_text(ME, "такси 5")

    assert (api.created[0]["account_id"], api.created[0]["currency"]) == ("dollars", "BYN")


async def test_category_then_account_are_asked_in_turn(entry: QuickEntry, api: FakeApi) -> None:
    api.accounts = [account("card", "BYN"), account("cash", "BYN")]

    category = await entry.handle_text(ME, "кофе 5")
    account_question = await entry.choose(ME, data_of(category, "Продукты"))
    await entry.choose(ME, data_of(account_question, "Card"))

    assert (api.created[0]["category_id"], api.created[0]["account_id"]) == ("food", "card")


async def test_a_question_is_answered_once(entry: QuickEntry, api: FakeApi) -> None:
    question = await entry.handle_text(ME, "кофе 5")
    await entry.choose(ME, data_of(question, "Такси"))

    again = await entry.choose(ME, data_of(question, "Такси"))

    assert again == Reply("Эта запись устарела. Отправьте сообщение ещё раз.")
    assert len(api.created) == 1


@pytest.mark.parametrize(
    "forge",
    [
        lambda data: data,  # someone else presses the button
        lambda data: data.rsplit(":", 1)[0] + ":7",
        lambda data: data.rsplit(":", 1)[0] + ":x",
        lambda data: data + ":1",
        lambda _: "qe:missing:0",
        lambda _: "qe",
    ],
    ids=["other-user", "index-out-of-range", "not-a-number", "extra-part", "unknown", "short"],
)
async def test_buttons_the_bot_did_not_send_to_this_member_are_refused(
    entry: QuickEntry, api: FakeApi, forge: Any
) -> None:
    question = await entry.handle_text(ME, "кофе 5")
    who = OTHER if forge("x") == "x" else ME

    reply = await entry.choose(who, forge(data_of(question, "Такси")))

    assert reply.text == messages.ENTRY_EXPIRED
    assert api.created == []


async def test_old_questions_are_forgotten_beyond_the_limit(
    entry: QuickEntry, api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quick_entry, "MAX_PENDING", 1)
    first = await entry.handle_text(ME, "кофе 5")
    second = await entry.handle_text(ME, "чай 3")

    assert (await entry.choose(ME, data_of(first, "Такси"))).text == messages.ENTRY_EXPIRED
    await entry.choose(ME, data_of(second, "Такси"))
    assert len(api.created) == 1


async def test_at_most_the_option_limit_is_offered(
    entry: QuickEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quick_entry, "MAX_OPTIONS", 2)

    question = await entry.handle_text(ME, "кофе 5")

    assert labels(question) == [["Продукты", "Такси"]]


async def test_a_message_that_is_not_an_entry_gets_the_reason(entry: QuickEntry) -> None:
    assert await entry.handle_text(ME, "привет") == Reply(
        "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."
    )


@pytest.mark.parametrize(("method", "path"), [("GET", "/me/settings"), ("POST", "/operations")])
async def test_api_errors_while_recording_are_explained(
    entry: QuickEntry, api: FakeApi, method: str, path: str
) -> None:
    api.failures[(method, path)] = ApiError(503, "rates_unavailable", "")

    reply = await entry.handle_text(ME, "продукты 5")

    assert reply == Reply("Курсы валют сейчас недоступны. Попробуйте чуть позже.")


async def test_api_errors_after_a_choice_are_explained(entry: QuickEntry, api: FakeApi) -> None:
    question = await entry.handle_text(ME, "кофе 5")
    api.failures[("POST", "/operations")] = ApiError(422, "archived", "")

    reply = await entry.choose(ME, data_of(question, "Такси"))

    assert reply == Reply("Этот счёт или категория в архиве.")


async def test_undo_deletes_the_operation(entry: QuickEntry, api: FakeApi) -> None:
    recorded = await entry.handle_text(ME, "продукты 5")

    reply = await entry.undo(ME, data_of(recorded, "Отменить"))

    assert api.deleted == ["/operations/00000000-0000-0000-0000-000000000001"]
    assert reply == Reply("Запись отменена.")


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (ApiError(404, "not_found", ""), "Этой записи уже нет."),
        (ApiError(403, "permission_denied", ""), "Что-то пошло не так. Попробуйте ещё раз."),
    ],
)
async def test_undo_explains_why_it_could_not(
    entry: QuickEntry, api: FakeApi, error: ApiError, text: str
) -> None:
    api.failures[("DELETE", "/operations/00000000-0000-0000-0000-000000000001")] = error

    assert await entry.undo(ME, "undo:00000000-0000-0000-0000-000000000001") == Reply(text)


@pytest.mark.parametrize("data", ["undo:../accounts", "undo:", "undo"])
async def test_an_undo_button_the_bot_did_not_send_is_refused(
    entry: QuickEntry, api: FakeApi, data: str
) -> None:
    assert await entry.undo(ME, data) == Reply(messages.ENTRY_EXPIRED)
    assert api.deleted == []
