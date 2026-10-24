"""NBRB client against responses recorded from api.nbrb.by (no network in tests)."""

import json
import ssl
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from family_pnl.domain.currency import Currency
from family_pnl.integrations import nbrb
from family_pnl.integrations.nbrb import NbrbClient, RateSourceUnavailableError, create_http_client

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nbrb"


def recorded(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def client_returning(
    handler: httpx.MockTransport | None = None, *, body: bytes = b"[]", status: int = 200
) -> tuple[NbrbClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body, headers={"content-type": "application/json"})

    transport = handler or httpx.MockTransport(respond)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.nbrb.by")
    return NbrbClient(http), seen


async def test_rates_are_byn_per_unit_with_the_scale_applied() -> None:
    client, _ = client_returning(body=recorded("rates_2026-10-20.json"))

    rates = await client.rates_on(date(2026, 10, 20))

    assert rates == {
        Currency.USD: Decimal("2.9950"),
        Currency.RUB: Decimal("0.036127"),  # 3.6127 BYN per 100 RUB
    }


async def test_rates_are_parsed_as_exact_decimals_never_floats() -> None:
    client, _ = client_returning(body=recorded("rates_2026-10-24.json"))

    rates = await client.rates_on(date(2026, 10, 24))

    assert all(type(rate) is Decimal for rate in rates.values())
    assert str(rates[Currency.USD]) == "2.9543"


async def test_the_request_asks_for_daily_rates_on_the_given_date() -> None:
    client, seen = client_returning(body=recorded("rates_2026-10-20.json"))

    await client.rates_on(date(2026, 10, 20))

    assert len(seen) == 1
    assert seen[0].url.path == "/exrates/rates"
    assert dict(seen[0].url.params) == {"ondate": "2026-10-20", "periodicity": "0"}


async def test_a_date_without_published_rates_returns_nothing() -> None:
    client, _ = client_returning(body=recorded("rates_unpublished.json"))

    assert await client.rates_on(date(2030, 1, 1)) == {}


async def test_rates_published_for_another_date_are_ignored() -> None:
    body = json.dumps(
        [
            {
                "Cur_Abbreviation": "USD",
                "Cur_Scale": 1,
                "Cur_OfficialRate": 3.0,
                "Date": "2026-10-19T00:00:00",
            }
        ]
    ).encode()
    client, _ = client_returning(body=body)

    assert await client.rates_on(date(2026, 10, 20)) == {}


@pytest.mark.parametrize("status", [500, 502, 503, 404])
async def test_http_errors_mean_the_source_is_unavailable(status: int) -> None:
    client, _ = client_returning(status=status, body=b"oops")

    with pytest.raises(RateSourceUnavailableError, match=str(status)):
        await client.rates_on(date(2026, 10, 20))


async def test_timeouts_mean_the_source_is_unavailable() -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = client_returning(httpx.MockTransport(time_out))

    with pytest.raises(RateSourceUnavailableError, match="ReadTimeout"):
        await client.rates_on(date(2026, 10, 20))


async def test_connection_errors_mean_the_source_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, _ = client_returning(httpx.MockTransport(refuse))

    with pytest.raises(RateSourceUnavailableError):
        await client.rates_on(date(2026, 10, 20))


@pytest.mark.parametrize(
    "body",
    [
        b"<html>maintenance</html>",
        b'{"error": "unexpected object"}',
        b'[{"Cur_Abbreviation": "USD"}]',
        b'[{"Cur_Abbreviation": "USD", "Cur_Scale": 0, "Cur_OfficialRate": 3.0,'
        b' "Date": "2026-10-20T00:00:00"}]',
        b'[{"Cur_Abbreviation": "USD", "Cur_Scale": 1, "Cur_OfficialRate": -3.0,'
        b' "Date": "2026-10-20T00:00:00"}]',
    ],
    ids=["not-json", "not-a-list", "missing-fields", "zero-scale", "negative-rate"],
)
async def test_malformed_responses_mean_the_source_is_unavailable(body: bytes) -> None:
    client, _ = client_returning(body=body)

    with pytest.raises(RateSourceUnavailableError, match="unexpected response"):
        await client.rates_on(date(2026, 10, 20))


async def test_default_http_client_points_at_nbrb_with_a_short_timeout() -> None:
    http = create_http_client()
    try:
        assert str(http.base_url) == "https://api.nbrb.by"
        assert http.timeout == httpx.Timeout(10.0)
    finally:
        await http.aclose()


def test_clients_share_one_tls_context_that_verifies_certificates() -> None:
    context = nbrb._tls_context()

    assert context is nbrb._tls_context()  # built once per process
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
