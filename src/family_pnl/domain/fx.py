"""Exchange rates as BYN per unit, and conversions between any two currencies.

The National Bank of Belarus quotes every currency against BYN, so a cross rate is derived
through BYN: RUB → USD = (BYN per RUB) / (BYN per USD). Conversions multiply and divide in
one step and are not rounded; callers round once at the end (Money.rounded).
"""

from collections.abc import Mapping
from decimal import Decimal

from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money

_ONE = Decimal(1)


class MissingRateError(LookupError):
    pass


class Rates:
    """BYN per one unit of each quoted currency, for one date."""

    def __init__(self, byn_per_unit: Mapping[Currency, Decimal]) -> None:
        if Currency.BYN in byn_per_unit:
            raise ValueError("BYN is the base currency and must not be quoted")
        for currency, rate in byn_per_unit.items():
            if rate <= 0:
                raise ValueError(f"rate for {currency} must be positive, got {rate}")
        self._byn_per_unit = dict(byn_per_unit)

    def byn_per_unit(self, currency: Currency) -> Decimal:
        if currency is Currency.BYN:
            return _ONE
        try:
            return self._byn_per_unit[currency]
        except KeyError:
            raise MissingRateError(f"no rate for {currency}") from None

    def rate(self, source: Currency, target: Currency) -> Decimal:
        """Units of `target` per one unit of `source`."""
        if source is target:
            return _ONE
        return self.byn_per_unit(source) / self.byn_per_unit(target)


def convert(money: Money, target: Currency, rates: Rates) -> Money:
    """Convert exactly; the result is not rounded."""
    if money.currency is target:
        return money
    amount = money.amount * rates.byn_per_unit(money.currency) / rates.byn_per_unit(target)
    return Money(amount, target)
