"""Dates outside 2000-01-01..2099-12-31 are refused with 422, never a server error."""

import pytest
from httpx import AsyncClient

from tests.integration.helpers import Actor, sign_up


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


OUT_OF_RANGE = [
    "/budgets/0000-05",
    "/budgets/0001-01",
    "/budgets/1999-12",
    "/budgets/2100-01",
    "/reports?from=0001-01-01&to=0001-01-31",
    "/reports?from=2026-10-01&to=2100-01-01",
    "/fx/rates?date=0001-01-02",
    "/operations?date_from=0001-01-01",
    "/operations?date_to=2100-01-01",
]


async def test_dates_out_of_range_are_rejected(client: AsyncClient, anna: Actor) -> None:
    # One user for every path: each case is only a request.
    answers = {}
    for path in OUT_OF_RANGE:
        response = await client.get(path, headers=anna.headers)
        answers[path] = (response.status_code, response.json()["error"]["code"])

    assert answers == dict.fromkeys(OUT_OF_RANGE, (422, "request_invalid"))


async def test_an_operation_dated_out_of_range_is_rejected(
    client: AsyncClient, anna: Actor
) -> None:
    response = await client.post(
        "/operations",
        headers=anna.headers,
        json={
            "type": "transfer",
            "amount": "1",
            "account_id": "0b8f6a0e-2f5a-4d43-9e86-3d2a0a6c1f11",
            "target_account_id": "6f1d1b8a-0c0a-4f0e-8c2b-1a4b8a2e9d22",
            "operation_date": "0001-01-01",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


async def test_the_first_and_last_months_work(client: AsyncClient, anna: Actor) -> None:
    first = await client.get("/budgets/2000-01", headers=anna.headers)
    last = await client.get("/budgets/2099-12", headers=anna.headers)

    assert first.status_code == last.status_code == 200
