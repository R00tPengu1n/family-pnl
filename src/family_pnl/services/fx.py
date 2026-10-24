"""Exchange rates for a date (ADR-0008).

Order of preference for each currency:
1. the stored official rate for that date;
2. the rate fetched from NBRB for that date (then stored for good);
3. the nearest earlier stored rate (the date is not published yet);
4. with nothing stored, earlier days fetched from NBRB, at most a week back.
If NBRB is unavailable, the last known stored rate is used and a warning is logged.
Fallback rates are never stored under the requested date, so the real rate can still arrive.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import UnavailableError
from family_pnl.domain.currency import Currency
from family_pnl.domain.fx import Rates, convert
from family_pnl.domain.money import Money
from family_pnl.integrations.nbrb import QUOTED, RateSourceUnavailableError
from family_pnl.repositories.fx import FxRateRepository

WALK_BACK_DAYS = 7

logger = structlog.get_logger(__name__)


class RateSource(Protocol):
    async def rates_on(self, day: date) -> dict[Currency, Decimal]: ...


class RatesUnavailableError(UnavailableError):
    code = "rates_unavailable"


@dataclass(frozen=True, slots=True)
class Quote:
    currency: Currency
    byn_per_unit: Decimal
    rate_date: date  # the official date of the rate; earlier than requested on fallback


@dataclass(frozen=True, slots=True)
class RatesOnDate:
    requested: date
    quotes: Mapping[Currency, Quote]

    def rates(self) -> Rates:
        return Rates({currency: q.byn_per_unit for currency, q in self.quotes.items()})

    def convert(self, money: Money, target: Currency) -> Money:
        return convert(money, target, self.rates())


class RateService:
    def __init__(self, session: AsyncSession, source: RateSource, clock: Clock) -> None:
        self._session = session
        self._source = source
        self._clock = clock
        self._rates = FxRateRepository(session)

    async def rates_on(self, day: date) -> RatesOnDate:
        quotes = {
            c: Quote(c, row.byn_per_unit, day)
            for c, row in (await self._rates.on_date(day)).items()
        }
        if _complete(quotes):
            return RatesOnDate(day, quotes)

        try:
            fetched = await self._source.rates_on(day)
        except RateSourceUnavailableError as exc:
            logger.warning("fx_rate_source_unavailable", requested=day.isoformat(), error=str(exc))
            return await self._last_known(day, quotes)

        await self.store(day, fetched)
        quotes.update({c: Quote(c, rate, day) for c, rate in fetched.items() if c not in quotes})
        if not _complete(quotes):
            quotes = await self._fill_from_earlier(day, quotes)
        return RatesOnDate(day, quotes)

    async def store(self, day: date, rates: dict[Currency, Decimal]) -> None:
        await self._rates.add_missing(day, rates, fetched_at=self._clock.now())
        await self._session.commit()

    async def _last_known(self, day: date, quotes: dict[Currency, Quote]) -> RatesOnDate:
        for currency in QUOTED:
            if currency in quotes:
                continue
            row = await self._rates.latest_on_or_before(currency, day)
            if row is None:
                raise RatesUnavailableError("Exchange rates are unavailable right now")
            quotes[currency] = Quote(currency, row.byn_per_unit, row.rate_date)
        return RatesOnDate(day, quotes)

    async def _fill_from_earlier(
        self, day: date, quotes: dict[Currency, Quote]
    ) -> dict[Currency, Quote]:
        for currency in QUOTED:
            if currency in quotes:
                continue
            row = await self._rates.latest_on_or_before(currency, day)
            if row is not None:
                quotes[currency] = Quote(currency, row.byn_per_unit, row.rate_date)
        earlier = day
        while not _complete(quotes) and day - earlier < timedelta(days=WALK_BACK_DAYS):
            earlier -= timedelta(days=1)
            try:
                fetched = await self._source.rates_on(earlier)
            except RateSourceUnavailableError as exc:
                logger.warning(
                    "fx_rate_source_unavailable", requested=earlier.isoformat(), error=str(exc)
                )
                raise RatesUnavailableError("Exchange rates are unavailable right now") from exc
            await self.store(earlier, fetched)
            for currency, rate in fetched.items():
                quotes.setdefault(currency, Quote(currency, rate, earlier))
        if not _complete(quotes):
            raise RatesUnavailableError(f"No exchange rates published on or before {day}")
        return quotes


def _complete(quotes: Mapping[Currency, Quote]) -> bool:
    return all(currency in quotes for currency in QUOTED)
