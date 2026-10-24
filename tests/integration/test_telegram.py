"""Telegram linking and bot authentication (ADR-0007)."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.api.main import create_app
from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.models import User
from tests.integration.conftest import BOT_SECRET
from tests.integration.helpers import Actor, sign_up

BOT = {"X-Bot-Token": BOT_SECRET}
ANNA_TG = 5_000_000_001  # Telegram ids exceed 32 bits


async def link_code(client: AsyncClient, actor: Actor) -> str:
    response = await client.post("/me/telegram-link-code", headers=actor.headers)
    assert response.status_code == 201, response.text
    code: str = response.json()["code"]
    return code


async def bot_link(client: AsyncClient, code: str, telegram_id: int) -> Response:
    return await client.post(
        "/bot/link", headers=BOT, json={"code": code, "telegram_id": telegram_id}
    )


async def bot_token(client: AsyncClient, telegram_id: int) -> Response:
    return await client.post("/auth/telegram", headers=BOT, json={"telegram_id": telegram_id})


async def bot_register(client: AsyncClient, telegram_id: int, **extra: Any) -> Response:
    return await client.post(
        "/bot/register", headers=BOT, json={"telegram_id": telegram_id, **extra}
    )


def bearer(response: Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_link_code_is_shown_in_two_groups_and_lives_10_minutes(
    client: AsyncClient, clock: FrozenClock
) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.post("/me/telegram-link-code", headers=anna.headers)

    assert response.status_code == 201
    body = response.json()
    assert len(body["code"]) == 9
    assert body["code"][4] == "-"
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(minutes=10)


async def test_bot_links_the_telegram_account_with_the_code(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = await link_code(client, anna)

    # Typed by hand in the bot: lower case, a space instead of the hyphen.
    response = await bot_link(client, code.lower().replace("-", " "), ANNA_TG)

    assert response.status_code == 200
    assert response.json()["id"] == str(anna.user_id)
    assert response.json()["telegram_linked"] is True
    me = await client.get("/me", headers=anna.headers)
    assert me.json()["telegram_linked"] is True


async def test_a_link_code_works_only_once(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = await link_code(client, anna)
    assert (await bot_link(client, code, ANNA_TG)).status_code == 200

    response = await bot_link(client, code, 777)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "link_code_invalid"


async def test_a_link_code_expires_after_10_minutes(
    client: AsyncClient, clock: FrozenClock
) -> None:
    anna = await sign_up(client, "anna@example.com")
    code = await link_code(client, anna)

    clock.advance(timedelta(minutes=10))

    assert (await bot_link(client, code, ANNA_TG)).status_code == 422


@pytest.mark.parametrize("code", ["ABCD-EFGH", "not a code", ""])
async def test_unknown_or_malformed_codes_are_invalid(client: AsyncClient, code: str) -> None:
    response = await bot_link(client, code, ANNA_TG)

    assert response.status_code == 422


async def test_a_telegram_account_can_belong_to_one_user_only(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    ivan = await sign_up(client, "ivan@example.com")
    await bot_link(client, await link_code(client, anna), ANNA_TG)

    response = await bot_link(client, await link_code(client, ivan), ANNA_TG)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "telegram_taken"


async def test_a_user_with_telegram_linked_cannot_link_another_account(
    client: AsyncClient,
) -> None:
    anna = await sign_up(client, "anna@example.com")
    await bot_link(client, await link_code(client, anna), ANNA_TG)

    response = await bot_link(client, await link_code(client, anna), 999)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "telegram_already_linked"


async def test_bot_exchanges_a_linked_telegram_id_for_a_user_token(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    await bot_link(client, await link_code(client, anna), ANNA_TG)

    response = await bot_token(client, ANNA_TG)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 15 * 60
    me = await client.get("/me", headers=bearer(response))
    assert me.json()["id"] == str(anna.user_id)


async def test_unknown_telegram_id_is_not_registered(client: AsyncClient) -> None:
    response = await bot_token(client, 123)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "telegram_not_registered"


async def test_bot_registers_a_telegram_only_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await bot_register(client, ANNA_TG, display_name="Анна", household_name="Ивановы")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] is None
    assert body["display_name"] == "Анна"
    assert body["telegram_linked"] is True
    assert body["role"] == "owner"
    assert body["household"]["name"] == "Ивановы"
    assert (await bot_token(client, ANNA_TG)).status_code == 200
    stored = await db_session.scalar(select(User).where(User.telegram_id == ANNA_TG))
    assert stored is not None
    assert stored.password_hash is None


async def test_registering_a_known_telegram_id_is_a_conflict(client: AsyncClient) -> None:
    await bot_register(client, ANNA_TG)

    response = await bot_register(client, ANNA_TG)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "telegram_taken"


async def test_bot_registration_with_an_invite_joins_that_household(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    invite = (await client.post("/household/invites", headers=anna.headers)).json()["code"]

    response = await bot_register(client, 6_000_000_002, invite_code=invite)

    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert response.json()["household"]["id"] == str(anna.household_id)


async def test_bot_registration_with_a_bad_invite_creates_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await bot_register(client, ANNA_TG, invite_code="x" * 22)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invite_invalid"
    users = await db_session.scalar(select(func.count()).select_from(User))
    assert users == 0


async def test_bot_tokens_carry_the_users_normal_permissions(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")
    invite = (await client.post("/household/invites", headers=anna.headers)).json()["code"]
    await bot_register(client, 6_000_000_002, invite_code=invite)
    member = await bot_token(client, 6_000_000_002)

    response = await client.post("/household/invites", headers=bearer(member))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path", ["/bot/link", "/bot/register", "/auth/telegram"], ids=["link", "register", "token"]
)
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Bot-Token": "wrong-secret"}, {"X-Bot-Token": BOT_SECRET + "x"}],
    ids=["missing", "wrong", "longer"],
)
async def test_bot_endpoints_require_the_bot_secret(
    client: AsyncClient, path: str, headers: dict[str, str]
) -> None:
    response = await client.post(path, headers=headers, json={"telegram_id": 1, "code": "x"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "bot_unauthorized"


async def test_bot_endpoints_are_off_without_a_configured_secret(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"bot_api_secret": None}))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            response = await http.post("/auth/telegram", headers=BOT, json={"telegram_id": 1})
    finally:
        await app.state.engine.dispose()
        await app.state.redis.aclose()
        await app.state.nbrb_http.aclose()

    assert response.status_code == 401


async def test_link_code_requires_a_signed_in_user(client: AsyncClient) -> None:
    assert (await client.post("/me/telegram-link-code")).status_code == 401


@pytest.mark.parametrize("telegram_id", [0, -5, 2**63])
async def test_telegram_ids_must_be_positive_64_bit_integers(
    client: AsyncClient, telegram_id: int
) -> None:
    assert (await bot_register(client, telegram_id)).status_code == 422
