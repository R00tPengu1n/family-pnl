from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money
from family_pnl.services.fx import RatesOnDate


class RateOut(BaseModel):
    currency: Currency
    byn_per_unit: Decimal
    rate_date: date


class RatesResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-10-20",
                    "base": "BYN",
                    "rates": [
                        {"currency": "RUB", "byn_per_unit": "0.036127", "rate_date": "2026-10-20"},
                        {"currency": "USD", "byn_per_unit": "2.9950", "rate_date": "2026-10-20"},
                    ],
                }
            ]
        }
    )

    date: date
    base: Literal["BYN"] = "BYN"
    rates: list[RateOut]

    @classmethod
    def of(cls, result: RatesOnDate) -> "RatesResponse":
        quotes = sorted(result.quotes.values(), key=lambda q: q.currency.value)
        return cls(
            date=result.requested,
            rates=[
                RateOut(currency=q.currency, byn_per_unit=q.byn_per_unit, rate_date=q.rate_date)
                for q in quotes
            ],
        )


class ConvertResponse(BaseModel):
    amount: Decimal
    currency: Currency
    converted: Decimal
    converted_currency: Currency
    rate: Decimal
    date: date

    @classmethod
    def of(cls, money: Money, target: Currency, result: RatesOnDate) -> "ConvertResponse":
        return cls(
            amount=money.amount,
            currency=money.currency,
            converted=result.convert(money, target).rounded().amount,
            converted_currency=target,
            rate=result.rates().rate(money.currency, target),
            date=result.requested,
        )
