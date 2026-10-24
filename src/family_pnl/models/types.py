"""Column types shared by several models."""

from enum import StrEnum

from sqlalchemy import Enum

from family_pnl.domain.currency import Currency


def checked_enum(enum: type[StrEnum], name: str) -> Enum:
    """A string column with a CHECK, not a native enum: adding a value is a plain migration."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum),
        values_callable=lambda members: [member.value for member in members],
    )


def currency_column() -> Enum:
    return checked_enum(Currency, "currency")
