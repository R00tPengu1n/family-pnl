"""Conversions through BYN quotes: NBRB publishes every rate as BYN per unit of a currency."""

from decimal import Decimal

import pytest

from family_pnl.domain.currency import Currency
from family_pnl.domain.fx import MissingRateError, Rates, convert
from family_pnl.domain.money import Money

# BYN per one unit; NBRB quotes RUB per 100, normalised to one rouble here.
USD = Decimal("3.2737")
RUB = Decimal("0.034567")
RATES = Rates({Currency.USD: USD, Currency.RUB: RUB})


def test_byn_is_always_one() -> None:
    assert RATES.byn_per_unit(Currency.BYN) == Decimal(1)


def test_quoted_rates_are_returned_as_given() -> None:
    assert RATES.byn_per_unit(Currency.USD) == USD


def test_rate_between_two_quoted_currencies_goes_through_byn() -> None:
    assert RATES.rate(Currency.RUB, Currency.USD) == RUB / USD
    assert RATES.rate(Currency.USD, Currency.RUB) == USD / RUB


def test_rate_of_a_currency_to_itself_is_one() -> None:
    assert RATES.rate(Currency.USD, Currency.USD) == Decimal(1)


@pytest.mark.parametrize(
    ("amount", "source", "target", "expected"),
    [
        ("100", Currency.USD, Currency.BYN, "327.37"),
        ("327.37", Currency.BYN, Currency.USD, "100.00"),
        ("1000", Currency.RUB, Currency.BYN, "34.57"),  # 34.567 rounds half up
        ("100", Currency.RUB, Currency.USD, "1.06"),  # 3.4567 / 3.2737 = 1.05590...
        ("25", Currency.USD, Currency.RUB, "2367.65"),  # 81.8425 / 0.034567 = 2367.65...
    ],
)
def test_conversion_rounds_once_at_the_end(
    amount: str, source: Currency, target: Currency, expected: str
) -> None:
    converted = convert(Money(Decimal(amount), source), target, RATES)

    assert converted.rounded() == Money(Decimal(expected), target)


def test_conversion_is_exact_until_rounded() -> None:
    converted = convert(Money(Decimal("100"), Currency.RUB), Currency.USD, RATES)

    assert converted.amount == Decimal("100") * RUB / USD


def test_converting_to_the_same_currency_returns_the_same_money() -> None:
    money = Money(Decimal("12.34"), Currency.BYN)

    assert convert(money, Currency.BYN, RATES) is money


def test_summing_exact_conversions_before_rounding_avoids_drift() -> None:
    # 300 conversions of 0.01 RUB: rounded one by one, each would become 0.00 USD.
    exact = sum(
        (convert(Money(Decimal("0.01"), Currency.RUB), Currency.USD, RATES) for _ in range(300)),
        start=Money.zero(Currency.USD),
    )

    assert exact.rounded() == Money(Decimal("0.03"), Currency.USD)


def test_a_missing_quote_is_an_error() -> None:
    rates = Rates({Currency.USD: USD})

    with pytest.raises(MissingRateError, match=r"^no rate for RUB$"):
        rates.rate(Currency.RUB, Currency.USD)


@pytest.mark.parametrize("bad", ["0", "-1.5", "-0.01"])
def test_rates_must_be_positive(bad: str) -> None:
    with pytest.raises(ValueError, match=rf"^rate for USD must be positive, got {bad}$"):
        Rates({Currency.USD: Decimal(bad)})


def test_a_byn_quote_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^BYN is the base currency and must not be quoted$"):
        Rates({Currency.BYN: Decimal(1)})


def test_the_smallest_positive_rate_is_accepted() -> None:
    assert Rates({Currency.USD: Decimal("0.00000001")}).byn_per_unit(Currency.USD) > 0
