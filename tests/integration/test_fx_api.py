from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from family_pnl.api.deps import get_rate_source
from family_pnl.core.clock import FrozenClock
from tests.integration.helpers import Actor, sign_up
from tests.integration.test_rate_service import RATES_MONDAY, RATES_TUESDAY, FakeSource

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    fake = FakeSource({MONDAY: RATES_MONDAY, TUESDAY: RATES_TUESDAY})
    app.dependency_overrides[get_rate_source] = lambda: fake
    return fake


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


async def test_rates_on_a_date(client: AsyncClient, anna: Actor, source: FakeSource) -> None:
    response = await client.get("/fx/rates", params={"date": "2026-10-20"}, headers=anna.headers)

    assert response.status_code == 200
    assert response.json() == {
        "date": "2026-10-20",
        "base": "BYN",
        "rates": [
            {"currency": "RUB", "byn_per_unit": "0.036127", "rate_date": "2026-10-20"},
            {"currency": "USD", "byn_per_unit": "2.9950", "rate_date": "2026-10-20"},
        ],
    }


async def test_rates_default_to_today_in_the_household_time_zone(
    client: AsyncClient, anna: Actor, source: FakeSource, clock: FrozenClock
) -> None:
    # 22:30 UTC on Monday is already Tuesday 01:30 in Minsk (UTC+3).
    clock.set(clock.now().replace(year=2026, month=10, day=19, hour=22, minute=30))

    response = await client.get("/fx/rates", headers=anna.headers)

    assert response.json()["date"] == "2026-10-20"
    assert source.calls == [TUESDAY]


async def test_a_fallback_rate_shows_its_own_date(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    await client.get("/fx/rates", params={"date": "2026-10-19"}, headers=anna.headers)

    response = await client.get("/fx/rates", params={"date": "2026-11-30"}, headers=anna.headers)

    rate_dates = {r["currency"]: r["rate_date"] for r in response.json()["rates"]}
    # Only Monday is stored and 30 November is not published: Monday's rates, labelled so.
    assert rate_dates == {"RUB": "2026-10-19", "USD": "2026-10-19"}


async def test_rates_unavailable_is_503(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    source.down = True

    response = await client.get("/fx/rates", params={"date": "2026-10-20"}, headers=anna.headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rates_unavailable"


async def test_convert_uses_the_rate_of_the_date_and_rounds_once(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    response = await client.get(
        "/fx/convert",
        params={"amount": "100", "from": "USD", "to": "RUB", "date": "2026-10-20"},
        headers=anna.headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "amount": "100",
        "currency": "USD",
        "converted": "8290.20",
        "converted_currency": "RUB",
        "rate": str(Decimal("2.9950") / Decimal("0.036127")),
        "date": "2026-10-20",
    }


async def test_convert_keeps_full_precision_of_the_input(
    client: AsyncClient, anna: Actor, source: FakeSource
) -> None:
    response = await client.get(
        "/fx/convert",
        params={"amount": "0.1", "from": "BYN", "to": "BYN", "date": "2026-10-20"},
        headers=anna.headers,
    )

    assert response.json()["converted"] == "0.10"
    assert response.json()["rate"] == "1"


@pytest.mark.parametrize(
    "params",
    [
        {"amount": "abc", "from": "USD", "to": "RUB"},
        {"amount": "10", "from": "EUR", "to": "RUB"},
        {"amount": "NaN", "from": "USD", "to": "RUB"},
        {"amount": "-5", "from": "USD", "to": "RUB"},
        {"amount": "1" * 20, "from": "USD", "to": "RUB"},
    ],
    ids=["not-a-number", "unknown-currency", "nan", "negative", "too-large"],
)
async def test_convert_rejects_bad_input(
    client: AsyncClient, anna: Actor, source: FakeSource, params: dict[str, str]
) -> None:
    response = await client.get("/fx/convert", params=params, headers=anna.headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


@pytest.mark.parametrize("path", ["/fx/rates", "/fx/convert?amount=1&from=USD&to=BYN"])
async def test_fx_endpoints_require_authentication(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401
