"""A Telegram-only user adds an email and password with a code from the bot."""

from datetime import timedelta

import pytest
from httpx import AsyncClient, Response

from family_pnl.core.clock import FrozenClock
from family_pnl.repositories.identity import UserRepository
from tests.integration.conftest import BOT_SECRET
from tests.integration.helpers import PASSWORD, sign_up

BOT = {"X-Bot-Token": BOT_SECRET}
ANNA = 5000000001


@pytest.fixture
async def anna_code(client: AsyncClient) -> str:
    """Anna registered through the bot and asked it for a credentials code."""
    registered = await client.post("/bot/register", headers=BOT, json={"telegram_id": ANNA})
    assert registered.status_code == 201, registered.text
    return await credentials_code(client)


async def credentials_code(client: AsyncClient, telegram_id: int = ANNA) -> str:
    response = await client.post(
        "/bot/credentials-code", headers=BOT, json={"telegram_id": telegram_id}
    )
    assert response.status_code == 201, response.text
    code: str = response.json()["code"]
    return code


async def set_credentials(
    client: AsyncClient, code: str, email: str = "anna@example.com", password: str = PASSWORD
) -> Response:
    return await client.post(
        "/auth/credentials", json={"code": code, "email": email, "password": password}
    )


async def test_a_telegram_user_sets_an_email_and_password_and_logs_in(
    client: AsyncClient, anna_code: str
) -> None:
    response = await set_credentials(client, anna_code, email=" Anna@Example.com ")

    assert response.status_code == 200
    assert (response.json()["email"], response.json()["telegram_linked"]) == (
        "anna@example.com",
        True,
    )
    login = await client.post(
        "/auth/login", json={"email": "anna@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_a_code_works_once(client: AsyncClient, anna_code: str) -> None:
    await set_credentials(client, anna_code)

    again = await set_credentials(client, anna_code, email="other@example.com")

    assert again.status_code == 422
    assert again.json()["error"]["code"] == "link_code_invalid"


async def test_a_code_expires_after_ten_minutes(
    client: AsyncClient, anna_code: str, clock: FrozenClock
) -> None:
    clock.advance(timedelta(minutes=10))

    response = await set_credentials(client, anna_code)

    assert response.json()["error"]["code"] == "link_code_invalid"


async def test_codes_of_one_purpose_do_not_work_for_the_other(
    client: AsyncClient, anna_code: str
) -> None:
    ivan = await sign_up(client, "ivan@example.com")
    link = (await client.post("/me/telegram-link-code", headers=ivan.headers)).json()["code"]

    as_link = await client.post(
        "/bot/link", headers=BOT, json={"code": anna_code, "telegram_id": 5000000002}
    )
    as_credentials = await set_credentials(client, link, email="new@example.com")

    assert as_link.json()["error"]["code"] == "link_code_invalid"
    assert as_credentials.json()["error"]["code"] == "link_code_invalid"


async def test_an_account_with_an_email_gets_no_code(client: AsyncClient) -> None:
    ivan = await sign_up(client, "ivan@example.com")
    link = (await client.post("/me/telegram-link-code", headers=ivan.headers)).json()["code"]
    await client.post("/bot/link", headers=BOT, json={"code": link, "telegram_id": ANNA})

    response = await client.post("/bot/credentials-code", headers=BOT, json={"telegram_id": ANNA})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credentials_already_set"


async def test_an_unknown_telegram_user_gets_no_code(client: AsyncClient) -> None:
    response = await client.post("/bot/credentials-code", headers=BOT, json={"telegram_id": 7})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "telegram_not_registered"


async def test_the_code_endpoint_is_for_the_bot_only(client: AsyncClient) -> None:
    response = await client.post("/bot/credentials-code", json={"telegram_id": ANNA})

    assert response.status_code == 401


async def test_an_email_of_another_account_is_refused(client: AsyncClient, anna_code: str) -> None:
    await sign_up(client, "taken@example.com")

    response = await set_credentials(client, anna_code, email="taken@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_an_email_taken_at_the_same_moment_is_refused(
    client: AsyncClient, anna_code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other registration commits between the check and this commit.
    await sign_up(client, "taken@example.com")

    async def nobody(self: UserRepository, email: str) -> None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", nobody)

    response = await set_credentials(client, anna_code, email="taken@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_the_password_policy_applies(client: AsyncClient, anna_code: str) -> None:
    response = await set_credentials(client, anna_code, password="short")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "weak_password"


async def test_codes_cannot_be_guessed_without_limit(client: AsyncClient, anna_code: str) -> None:
    statuses = [(await set_credentials(client, "AAAA-AAAA")).status_code for _ in range(6)]

    assert statuses == [422] * 5 + [429]


async def test_a_second_code_is_refused_once_the_email_is_set(
    client: AsyncClient, anna_code: str
) -> None:
    second = await credentials_code(client)
    await set_credentials(client, anna_code)

    response = await set_credentials(client, second, email="again@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credentials_already_set"
