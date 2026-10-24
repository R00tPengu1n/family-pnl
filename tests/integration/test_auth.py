from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.core.security import hash_refresh_token
from family_pnl.models import Household, Membership, RefreshToken

PASSWORD = "correct horse battery"


async def register(client: AsyncClient, email: str, **extra: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def bearer(token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_registration_creates_an_owner_of_a_new_household(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await register(client, "Anna@Example.com", household_name="Ivanovs")

    assert body["email"] == "anna@example.com"
    assert body["role"] == "owner"
    assert body["household"]["name"] == "Ivanovs"
    assert body["household"]["timezone"] == "Europe/Minsk"
    memberships = await db_session.scalar(select(func.count()).select_from(Membership))
    households = await db_session.scalar(select(func.count()).select_from(Household))
    assert (memberships, households) == (1, 1)


async def test_household_name_has_a_default(client: AsyncClient) -> None:
    body = await register(client, "ivan@example.com")

    assert body["household"]["name"] == "Family"


async def test_duplicate_email_in_another_case_is_a_conflict(client: AsyncClient) -> None:
    await register(client, "anna@example.com")

    response = await client.post(
        "/auth/register", json={"email": "ANNA@example.com", "password": PASSWORD}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_invalid_email_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={"email": "anna", "password": PASSWORD})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


async def test_weak_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "anna@example.com", "password": "short"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "weak_password"


async def test_password_never_appears_in_validation_errors(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "not-an-email", "password": "p" * 5000}
    )

    assert response.status_code == 422
    assert "ppppp" not in response.text


async def test_login_returns_a_token_pair_and_stores_only_the_refresh_digest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "anna@example.com")

    tokens = await login(client, "Anna@Example.com")

    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    stored = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(str(tokens["refresh_token"]))
        )
    )
    assert stored is not None
    assert stored.expires_at - stored.issued_at == timedelta(days=30)


async def test_wrong_password_and_unknown_email_look_the_same(client: AsyncClient) -> None:
    await register(client, "anna@example.com")

    wrong = await client.post(
        "/auth/login", json={"email": "anna@example.com", "password": "wrong password!"}
    )
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"


async def test_me_returns_the_current_user(client: AsyncClient) -> None:
    registered = await register(client, "anna@example.com")
    tokens = await login(client, "anna@example.com")

    response = await client.get("/me", headers=bearer(tokens["access_token"]))

    assert response.status_code == 200
    assert response.json() == registered


async def test_me_without_a_token_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


async def test_me_with_a_garbage_token_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/me", headers=bearer("not.a.jwt"))

    assert response.status_code == 401


async def test_access_token_expires_after_15_minutes(
    client: AsyncClient, clock: FrozenClock
) -> None:
    await register(client, "anna@example.com")
    tokens = await login(client, "anna@example.com")

    clock.advance(timedelta(minutes=14, seconds=59))
    still_valid = await client.get("/me", headers=bearer(tokens["access_token"]))
    clock.advance(timedelta(seconds=1))
    expired = await client.get("/me", headers=bearer(tokens["access_token"]))

    assert still_valid.status_code == 200
    assert expired.status_code == 401


async def test_each_registered_user_gets_a_separate_household(client: AsyncClient) -> None:
    anna = await register(client, "anna@example.com")
    ivan = await register(client, "ivan@example.com")

    assert anna["household"]["id"] != ivan["household"]["id"]


async def test_household_name_is_trimmed_and_must_not_be_blank(client: AsyncClient) -> None:
    trimmed = await register(client, "anna@example.com", household_name="  Ivanovs  ")
    blank = await client.post(
        "/auth/register",
        json={"email": "ivan@example.com", "password": PASSWORD, "household_name": "   "},
    )

    assert trimmed["household"]["name"] == "Ivanovs"
    assert blank.status_code == 422
