from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from family_pnl.domain.currency import Currency
from family_pnl.models.base import Base


class FxRate(Base):
    """An official NBRB rate: BYN per one unit of a currency on a date. Never changes."""

    __tablename__ = "fx_rates"

    currency: Mapped[Currency] = mapped_column(
        Enum(
            Currency,
            name="currency",
            native_enum=False,
            create_constraint=True,
            length=3,
            values_callable=lambda currencies: [c.value for c in currencies],
        ),
        primary_key=True,
    )
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    # NUMERIC(18, 8) as in the spec: RUB per unit is about 0.036, eight places keep it exact.
    byn_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
