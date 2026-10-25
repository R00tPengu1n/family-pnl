"""/account and /input with a fake API client."""

from typing import Any, cast

import pytest

from family_pnl_bot.accounts import create_account, credentials_code
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.quick_entry import Button, Reply
from family_pnl_bot.reports import Reports

ME = 1
USAGE = "Напишите название и валюту: /account Карта BYN (добавьте «общий» для общего счёта)."


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.failure: ApiError | None = None

    async def request(self, telegram_id: int, method: str, path: str, *, json: Any = None) -> Any:
        if self.failure is not None:
            raise self.failure
        self.calls.append((method, path, json))
        return {"input_currency": "RUB", "display_currency": "RUB"} if method == "GET" else {}


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.mark.parametrize(
    ("args", "body", "reply"),
    [
        (
            "Карта BYN",
            {"name": "Карта", "type": "card", "currency": "BYN", "shared": False},
            "Счёт «Карта» в BYN создан.",
        ),
        (
            "Семейный кошелёк руб общий",
            {"name": "Семейный кошелёк", "type": "card", "currency": "RUB", "shared": True},
            "Общий счёт «Семейный кошелёк» в RUB создан.",
        ),
        (
            "Доллары $",
            {"name": "Доллары", "type": "card", "currency": "USD", "shared": False},
            "Счёт «Доллары» в USD создан.",
        ),
    ],
)
async def test_an_account_is_opened_from_the_bot(
    api: FakeApi, args: str, body: dict[str, Any], reply: str
) -> None:
    result = await create_account(cast(ApiClient, api), ME, args)

    assert api.calls == [("POST", "/accounts", body)]
    assert result == Reply(reply)


@pytest.mark.parametrize("args", [None, "", "Карта", "BYN", "Карта EUR", "общий", "Карта общий"])
async def test_without_a_name_and_a_currency_the_usage_is_shown(
    api: FakeApi, args: str | None
) -> None:
    assert await create_account(cast(ApiClient, api), ME, args) == Reply(USAGE)
    assert api.calls == []


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (ApiError(403, "permission_denied", ""), "Общий счёт может открыть только владелец семьи."),
        (ApiError(0, "api_unavailable", ""), "Сервис сейчас недоступен. Попробуйте чуть позже."),
    ],
)
async def test_refusals_are_explained(api: FakeApi, error: ApiError, text: str) -> None:
    api.failure = error

    assert await create_account(cast(ApiClient, api), ME, "Карта BYN общий") == Reply(text)


async def test_the_input_currency_is_chosen_with_buttons(api: FakeApi) -> None:
    reports = Reports(cast(ApiClient, api))

    question = await reports.currency(ME, "inp")
    done = await reports.set_currency(ME, "inp:BYN")

    assert question == Reply(
        "Сумма без валюты записывается в RUB. Выберите другую валюту:",
        ((Button("RUB", "inp:RUB"), Button("BYN", "inp:BYN"), Button("USD", "inp:USD")),),
    )
    assert api.calls[-1] == ("PATCH", "/me/settings", {"input_currency": "BYN"})
    assert done == Reply("Готово: сумма без валюты теперь в BYN.")


@pytest.mark.parametrize("data", ["xyz:BYN", "inp:EUR", "inp"])
async def test_currency_buttons_the_bot_did_not_send_are_refused(api: FakeApi, data: str) -> None:
    reply = await Reports(cast(ApiClient, api)).set_currency(ME, data)

    assert reply.text == "Эта запись устарела. Отправьте сообщение ещё раз."
    assert api.calls == []


class CodeApi:
    def __init__(self, error: ApiError | None = None) -> None:
        self.error = error

    async def credentials_code(self, telegram_id: int) -> str:
        if self.error is not None:
            raise self.error
        return "K7Q2-M9XD"


async def test_password_gives_a_code_and_never_asks_for_the_password() -> None:
    reply = await credentials_code(cast(ApiClient, CodeApi()), ME)

    assert reply.text == (
        "Код для email и пароля: K7Q2-M9XD, действует 10 минут.\n"
        "Отправьте его в API: POST /auth/credentials с полями code, email и password. "
        "Пароль в этот чат не пишите."
    )


async def test_an_account_with_a_password_is_told_so() -> None:
    api = CodeApi(ApiError(409, "credentials_already_set", ""))

    reply = await credentials_code(cast(ApiClient, api), ME)

    assert reply.text == "У вас уже есть email и пароль: входите через POST /auth/login."
