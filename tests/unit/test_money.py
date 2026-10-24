from decimal import Decimal

import pytest

from family_pnl.domain.currency import Currency
from family_pnl.domain.money import CurrencyMismatchError, Money


def test_currencies_are_the_three_of_the_spec() -> None:
    assert [c.value for c in Currency] == ["RUB", "BYN", "USD"]


@pytest.mark.parametrize("raw", ["rub", "RUB", " Rub "])
def test_currency_codes_are_parsed_case_insensitively(raw: str) -> None:
    assert Currency.parse(raw) is Currency.RUB


def test_unknown_currency_code_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^unsupported currency: EUR$"):
        Currency.parse(" EUR ")


def test_money_keeps_the_exact_decimal() -> None:
    money = Money(Decimal("10.125"), Currency.BYN)

    assert money.amount == Decimal("10.125")
    assert money.currency is Currency.BYN


@pytest.mark.parametrize("amount", [10.5, 1])
def test_money_rejects_anything_but_decimal(amount: object) -> None:
    expected = f"^Money amount must be a Decimal, got {type(amount).__name__}$"
    with pytest.raises(TypeError, match=expected):
        Money(amount, Currency.BYN)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_money_rejects_non_finite_amounts(amount: str) -> None:
    with pytest.raises(ValueError, match=r"^Money amount must be finite$"):
        Money(Decimal(amount), Currency.BYN)


@pytest.mark.parametrize(
    ("amount", "rounded"),
    [
        ("2.345", "2.35"),  # half up, not banker's rounding
        ("2.344", "2.34"),
        ("-2.345", "-2.35"),  # half away from zero
        ("2.5", "2.50"),
        ("7", "7.00"),
    ],
)
def test_rounding_is_half_up_to_cents(amount: str, rounded: str) -> None:
    result = Money(Decimal(amount), Currency.RUB).rounded()

    assert result == Money(Decimal(rounded), Currency.RUB)
    assert str(result.amount) == rounded


def test_same_currency_amounts_add_and_subtract_exactly() -> None:
    a = Money(Decimal("0.1"), Currency.USD)
    b = Money(Decimal("0.2"), Currency.USD)

    assert a + b == Money(Decimal("0.3"), Currency.USD)
    assert b - a == Money(Decimal("0.1"), Currency.USD)
    assert -a == Money(Decimal("-0.1"), Currency.USD)


def test_adding_different_currencies_is_refused() -> None:
    with pytest.raises(
        CurrencyMismatchError, match=r"^cannot combine RUB and USD without conversion$"
    ):
        _ = Money(Decimal(1), Currency.RUB) + Money(Decimal(1), Currency.USD)


def test_subtracting_different_currencies_is_refused() -> None:
    with pytest.raises(CurrencyMismatchError, match=r"^cannot combine RUB and BYN"):
        _ = Money(Decimal(1), Currency.RUB) - Money(Decimal(1), Currency.BYN)


def test_zero_of_a_currency() -> None:
    assert Money.zero(Currency.BYN) == Money(Decimal(0), Currency.BYN)


def test_bool_is_not_a_money_amount() -> None:
    with pytest.raises(TypeError):
        Money(True, Currency.BYN)  # bool is an int subclass, still not a Decimal
