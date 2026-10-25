"""Amounts and months as the bot writes them."""

from datetime import date
from decimal import Decimal

MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def amount(value: str | Decimal) -> str:
    """Two decimals, thousands split by spaces: 2 995.00. Straight from Decimal."""
    return f"{Decimal(value):,.2f}".replace(",", " ")


def money(value: str | Decimal, currency: str) -> str:
    return f"{amount(value)} {currency}"


def month_name(month: date) -> str:
    """Октябрь 2026."""
    return f"{MONTHS[month.month - 1].capitalize()} {month.year}"
