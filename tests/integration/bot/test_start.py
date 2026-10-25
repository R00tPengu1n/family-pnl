"""/start and /link replies against the real API (aiogram is not imported here)."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient
from pydantic import SecretStr, ValidationError

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.config import BotSettings
from family_pnl_bot.replies import link_reply, start_reply
from family_pnl_bot.throttle import AttemptLimiter
from tests.integration.helpers import sign_up

ANNA, IVAN = 5000000001, 5000000002
HELP = messages.HELP


@pytest.fixture
def limiter() -> AttemptLimiter:
    return AttemptLimiter(max_attempts=5, window_seconds=900)


async def invite_from(api: ApiClient, owner: int) -> str:
    code: str = (await api.request(owner, "POST", "/household/invites"))["code"]
    return code


async def test_a_new_telegram_user_gets_an_account_and_a_household(api: ApiClient) -> None:
    reply = await start_reply(api, ANNA, "Анна", None)

    assert reply == f"Готово! Создана семья «Family», вы — её владелец.\n{HELP}"
    assert (await api.me(ANNA)).role == "owner"


async def test_start_again_welcomes_back(api: ApiClient) -> None:
    await start_reply(api, ANNA, "Анна", None)

    assert await start_reply(api, ANNA, "Анна", None) == (
        f"С возвращением! Ваша семья — «Family».\n{HELP}"
    )


async def test_start_with_an_invite_joins_the_household(api: ApiClient) -> None:
    await start_reply(api, ANNA, "Анна", None)
    code = await invite_from(api, ANNA)

    reply = await start_reply(api, IVAN, "Иван", code)

    assert reply == f"Вы присоединились к семье «Family».\n{HELP}"
    ivan = await api.me(IVAN)
    assert (ivan.role, ivan.display_name) == ("member", "Иван")


async def test_a_registered_user_with_an_empty_household_joins_by_invite(
    api: ApiClient,
) -> None:
    await start_reply(api, ANNA, "Анна", None)
    await start_reply(api, IVAN, "Иван", None)
    code = await invite_from(api, ANNA)

    reply = await start_reply(api, IVAN, "Иван", code)

    assert reply == f"Вы присоединились к семье «Family».\n{HELP}"
    assert (await api.me(IVAN)).role == "member"


@pytest.mark.parametrize("registered", [False, True], ids=["new-user", "registered-user"])
async def test_a_bad_invite_is_explained_in_russian(api: ApiClient, registered: bool) -> None:
    if registered:
        await start_reply(api, IVAN, "Иван", None)

    reply = await start_reply(api, IVAN, "Иван", "NOPE-NOPE")

    assert reply == messages.ERRORS["invite_invalid"]
    assert reply == "Код приглашения не подходит или устарел. Попросите владельца прислать новый."


async def test_when_the_api_is_down_start_says_so() -> None:
    class DownApi:
        async def me(self, telegram_id: int) -> None:
            raise ApiError(0, "api_unavailable", "API request failed: ConnectError")

    reply = await start_reply(cast(ApiClient, DownApi()), ANNA, None, None)

    assert reply == "Сервис сейчас недоступен. Попробуйте чуть позже."


async def test_an_existing_api_account_is_linked_with_a_code(
    api: ApiClient, client: AsyncClient, limiter: AttemptLimiter
) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = (await client.post("/me/telegram-link-code", headers=anna.headers)).json()["code"]

    reply = await link_reply(api, limiter, ANNA, code)

    assert reply == "Telegram привязан к аккаунту anna@example.com."
    assert (await api.me(ANNA)).email == "anna@example.com"


async def test_a_linked_account_without_email_is_named_by_display_name() -> None:
    class LinkingApi:
        async def link(self, telegram_id: int, code: str) -> Any:
            return SimpleNamespace(email=None, display_name="Анна", household_name="Family")

    limiter = AttemptLimiter(5, 900)

    reply = await link_reply(cast(ApiClient, LinkingApi()), limiter, ANNA, "CODE")

    assert reply == "Telegram привязан к аккаунту Анна."


async def test_a_wrong_link_code_is_explained(api: ApiClient, limiter: AttemptLimiter) -> None:
    assert await link_reply(api, limiter, ANNA, "AAAA-AAAA") == (
        "Код не подходит или устарел. Запросите новый в приложении."
    )


@pytest.mark.parametrize("code", [None, ""])
async def test_link_without_a_code_shows_how(
    api: ApiClient, limiter: AttemptLimiter, code: str | None
) -> None:
    assert await link_reply(api, limiter, ANNA, code) == (
        "Отправьте код из приложения: /link K7Q2-M9XD"
    )


async def test_link_attempts_are_limited_per_telegram_user(api: ApiClient) -> None:
    limiter = AttemptLimiter(max_attempts=2, window_seconds=900)
    await link_reply(api, limiter, ANNA, "AAAA-AAAA")
    await link_reply(api, limiter, ANNA, "AAAA-AAAA")

    assert await link_reply(api, limiter, ANNA, "AAAA-AAAA") == (
        "Слишком много попыток. Попробуйте через 15 минут."
    )
    assert await link_reply(api, limiter, IVAN, "AAAA-AAAA") != messages.LINK_THROTTLED


def test_unknown_api_errors_get_a_general_text() -> None:
    assert messages.error_text(ApiError(500, "unknown", "")) == (
        "Что-то пошло не так. Попробуйте ещё раз."
    )


def test_settings_have_safe_defaults() -> None:
    settings = BotSettings(
        _env_file=None,
        telegram_bot_token=SecretStr("123456:test-token"),
        bot_api_secret=SecretStr("s" * 32),
    )

    assert (settings.api_url, settings.link_max_attempts, settings.link_window_seconds) == (
        "http://127.0.0.1:8000",
        5,
        900,
    )
    assert "test-token" not in repr(settings)


def test_a_missing_token_is_reported_without_the_other_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAMILY_PNL_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("FAMILY_PNL_BOT_API_SECRET", "bot-secret-value-of-32-characters!")

    with pytest.raises(ValidationError) as raised:
        BotSettings(_env_file=None)

    assert "telegram_bot_token" in str(raised.value)
    assert "bot-secret-value" not in str(raised.value)
