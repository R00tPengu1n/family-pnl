from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.models import FxRate


class FxRateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def on_date(self, day: date) -> dict[Currency, FxRate]:
        rows = await self._session.scalars(select(FxRate).where(FxRate.rate_date == day))
        return {row.currency: row for row in rows}

    async def latest_on_or_before(self, currency: Currency, day: date) -> FxRate | None:
        return await self._session.scalar(
            select(FxRate)
            .where(FxRate.currency == currency, FxRate.rate_date <= day)
            .order_by(FxRate.rate_date.desc())
            .limit(1)
        )

    async def add_missing(
        self, day: date, rates: dict[Currency, Decimal], fetched_at: datetime
    ) -> None:
        """Insert rates; a row that already exists wins (official rates never change)."""
        if not rates:
            return
        statement = insert(FxRate).values(
            [
                {
                    "currency": currency,
                    "rate_date": day,
                    "byn_per_unit": rate,
                    "fetched_at": fetched_at,
                }
                for currency, rate in rates.items()
            ]
        )
        await self._session.execute(statement.on_conflict_do_nothing())
