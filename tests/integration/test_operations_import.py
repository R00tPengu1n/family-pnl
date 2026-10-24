"""POST /operations/import: strict, lenient and dry-run imports of a CSV file."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.api.deps import get_rate_source
from family_pnl.core.clock import FrozenClock
from family_pnl.models import Notification
from family_pnl.services.csv_import import MAX_BYTES
from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import new_account
from tests.integration.test_rate_service import RATES_TUESDAY, TUESDAY, FakeSource

HEADER = "date,type,amount,account,category,currency,comment"
GOOD = "2026-10-20,expense,12.50,Card,Продукты,,Молоко"
SALARY = "2026-10-20,income,1000,Card,Зарплата,BYN,"
BAD = "2026-10-20,expense,0,Wallet,Продукты,,"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def anna(client: AsyncClient, source: FakeSource) -> Actor:
    actor = await sign_up(client, "anna@example.com")
    await new_account(client, actor, "BYN", "Card")
    return actor


async def upload(
    client: AsyncClient, actor: Actor, *rows: str, query: str = "", body: bytes | None = None
) -> Response:
    content = body if body is not None else "\n".join([HEADER, *rows]).encode("utf-8")
    return await client.post(
        f"/operations/import{query}",
        headers={**actor.headers, "Content-Type": "text/csv"},
        content=content,
    )


async def operations(client: AsyncClient, actor: Actor) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await client.get("/operations", headers=actor.headers)).json()[
        "items"
    ]
    return items


async def test_a_valid_file_is_imported(client: AsyncClient, anna: Actor) -> None:
    response = await upload(client, anna, GOOD, SALARY)

    assert response.status_code == 200
    assert response.json() == {
        "dry_run": False,
        "strict": True,
        "total_rows": 2,
        "valid_rows": 2,
        "imported": 2,
        "errors": [],
    }
    found = await operations(client, anna)
    assert sorted((o["type"], o["amount"], o["currency"], o["comment"]) for o in found) == [
        ("expense", "12.50", "BYN", "Молоко"),
        ("income", "1000.00", "BYN", None),
    ]
    assert {o["author_id"] for o in found} == {str(anna.user_id)}


async def test_in_strict_mode_one_bad_row_stops_the_whole_import(
    client: AsyncClient, anna: Actor
) -> None:
    response = await upload(client, anna, GOOD, BAD)

    body = response.json()
    assert (body["valid_rows"], body["imported"]) == (1, 0)
    assert body["errors"] == [
        {"row": 3, "column": "amount", "reason": "Must be positive and below one trillion"},
        {"row": 3, "column": "account", "reason": "No account named 'Wallet'"},
    ]
    assert await operations(client, anna) == []


async def test_without_strict_mode_the_valid_rows_are_imported(
    client: AsyncClient, anna: Actor
) -> None:
    response = await upload(client, anna, GOOD, BAD, SALARY, query="?strict=false")

    body = response.json()
    assert (body["strict"], body["total_rows"], body["valid_rows"], body["imported"]) == (
        False,
        3,
        2,
        2,
    )
    assert [e["row"] for e in body["errors"]] == [3, 3]
    assert len(await operations(client, anna)) == 2


async def test_a_dry_run_checks_and_imports_nothing(client: AsyncClient, anna: Actor) -> None:
    response = await upload(client, anna, GOOD, SALARY, query="?dry_run=true")

    body = response.json()
    assert (body["dry_run"], body["valid_rows"], body["imported"]) == (True, 2, 0)
    assert await operations(client, anna) == []


async def test_a_file_without_valid_rows_imports_nothing(client: AsyncClient, anna: Actor) -> None:
    body = (await upload(client, anna, BAD, query="?strict=false")).json()

    assert (body["valid_rows"], body["imported"]) == (0, 0)


async def test_a_file_of_only_a_header_imports_nothing(client: AsyncClient, anna: Actor) -> None:
    body = (await upload(client, anna)).json()

    assert (body["total_rows"], body["imported"], body["errors"]) == (0, 0, [])


async def test_imported_expenses_reach_budget_thresholds(
    client: AsyncClient, anna: Actor, db_session: AsyncSession
) -> None:
    food = next(
        c["id"]
        for c in (await client.get("/categories", headers=anna.headers)).json()
        if c["name"] == "Продукты"
    )
    await client.put(f"/budgets/2026-10/limits/{food}", headers=anna.headers, json={"amount": "20"})

    await upload(client, anna, GOOD, GOOD)

    payloads = [n.payload for n in (await db_session.scalars(select(Notification))).all()]
    assert sorted(p["threshold"] for p in payloads) == [80, 100]


async def test_names_of_another_household_are_unknown(client: AsyncClient, anna: Actor) -> None:
    bob = await sign_up(client, "bob@example.com")

    body = (await upload(client, bob, GOOD)).json()

    assert body["errors"] == [{"row": 2, "column": "account", "reason": "No account named 'Card'"}]


async def test_a_member_imports_into_the_shared_ledger(client: AsyncClient, anna: Actor) -> None:
    ivan = await join_household(client, anna, "ivan@example.com")

    body = (await upload(client, ivan, GOOD)).json()

    assert body["imported"] == 1
    assert [o["author_id"] for o in await operations(client, anna)] == [str(ivan.user_id)]


async def test_a_file_over_the_size_limit_is_rejected(client: AsyncClient, anna: Actor) -> None:
    response = await upload(client, anna, body=b"x" * (MAX_BYTES + 1))

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_import_file",
        "message": f"The file is larger than {MAX_BYTES} bytes",
        "details": None,
    }


async def test_a_file_that_cannot_be_read_is_rejected(client: AsyncClient, anna: Actor) -> None:
    response = await upload(client, anna, body=b"amount,comment\n1,x")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_import_file"


async def test_the_import_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/operations/import", content=HEADER.encode())

    assert response.status_code == 401
