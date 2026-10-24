"""Money as an exact Decimal amount in one currency.

Arithmetic and conversion stay exact; `rounded()` applies the single rounding step
(ROUND_HALF_UP to cents) at the end of a calculation. Rounding every intermediate result
would let small conversions drift in sums and reports.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from family_pnl.domain.currency import Currency

CENT = Decimal("0.01")


class CurrencyMismatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        # bool and int are rejected too: an amount must be a deliberate Decimal.
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"Money amount must be a Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError("Money amount must be finite")

    @classmethod
    def zero(cls, currency: Currency) -> "Money":
        return cls(Decimal(0), currency)

    def rounded(self) -> "Money":
        return Money(self.amount.quantize(CENT, rounding=ROUND_HALF_UP), self.currency)

    def __add__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def _same_currency(self, other: "Money") -> None:
        if other.currency is not self.currency:
            raise CurrencyMismatchError(
                f"cannot combine {self.currency} and {other.currency} without conversion"
            )
