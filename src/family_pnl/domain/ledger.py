"""Ledger vocabulary: account types."""

from enum import StrEnum


class AccountType(StrEnum):
    CARD = "card"
    CASH = "cash"
    SAVINGS = "savings"
