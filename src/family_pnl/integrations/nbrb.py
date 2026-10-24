"""Client of the National Bank of the Republic of Belarus exchange rate API.

`GET /exrates/rates?ondate=YYYY-MM-DD&periodicity=0` lists the daily rates set for a date
(weekends included; an empty list for dates not yet published). Each rate is BYN per
`Cur_Scale` units (RUB is quoted per 100); the client returns BYN per one unit.

Rates are parsed as Decimal straight from the JSON text, never through float. Every failure
of the source — network, HTTP status, unexpected payload — is RateSourceUnavailableError,
so the caller can fall back to the last known rate.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from family_pnl.domain.currency import Currency

BASE_URL = "https://api.nbrb.by"
QUOTED = (Currency.USD, Currency.RUB)


class RateSourceUnavailableError(Exception):
    """NBRB could not be reached or answered with something unusable."""


class NbrbClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def rates_on(self, day: date) -> dict[Currency, Decimal]:
        """BYN per unit of each quoted currency set for `day`; empty if not published yet."""
        try:
            response = await self._http.get(
                "/exrates/rates", params={"ondate": day.isoformat(), "periodicity": "0"}
            )
        except httpx.HTTPError as exc:
            raise RateSourceUnavailableError(f"NBRB request failed: {type(exc).__name__}") from exc
        if response.status_code != httpx.codes.OK:
            raise RateSourceUnavailableError(f"NBRB answered HTTP {response.status_code}")
        try:
            return _parse(response.text, day)
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            raise RateSourceUnavailableError("NBRB sent an unexpected response") from exc


def _parse(text: str, day: date) -> dict[Currency, Decimal]:
    payload: Any = json.loads(text, parse_float=Decimal, parse_int=Decimal)
    if not isinstance(payload, list):
        raise TypeError("expected a list of rates")
    rates: dict[Currency, Decimal] = {}
    for item in payload:
        code = item["Cur_Abbreviation"]
        if code not in QUOTED:
            continue
        scale, rate = Decimal(item["Cur_Scale"]), Decimal(item["Cur_OfficialRate"])
        published = datetime.fromisoformat(item["Date"]).date()
        if scale <= 0 or rate <= 0:
            raise ValueError(f"non-positive rate or scale for {code}")
        if published != day:
            continue  # a rate for another day is not this day's rate
        rates[Currency(code)] = rate / scale
    return rates


def create_http_client(base_url: str = BASE_URL) -> httpx.AsyncClient:
    # NBRB is slow at times; a short timeout lets the caller fall back quickly.
    return httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0))
