"""Ledger vocabulary and rules: accounts, categories and operations."""

import uuid
from enum import StrEnum

from family_pnl.core.errors import PermissionDeniedError, ValidationFailedError
from family_pnl.domain.identity import Role


class AccountType(StrEnum):
    CARD = "card"
    CASH = "cash"
    SAVINGS = "savings"


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class OperationType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class CategoryKindMismatchError(ValidationFailedError):
    code = "category_kind_mismatch"


# Created with every household. The names are data shown to Russian-speaking users of the bot.
DEFAULT_CATEGORIES: tuple[tuple[CategoryKind, str], ...] = (
    (CategoryKind.EXPENSE, "Продукты"),
    (CategoryKind.EXPENSE, "Кафе и рестораны"),
    (CategoryKind.EXPENSE, "Транспорт"),
    (CategoryKind.EXPENSE, "Жильё и коммунальные"),
    (CategoryKind.EXPENSE, "Связь и интернет"),
    (CategoryKind.EXPENSE, "Здоровье"),
    (CategoryKind.EXPENSE, "Одежда"),
    (CategoryKind.EXPENSE, "Дети"),
    (CategoryKind.EXPENSE, "Развлечения"),
    (CategoryKind.EXPENSE, "Подарки"),
    (CategoryKind.EXPENSE, "Другое"),
    (CategoryKind.INCOME, "Зарплата"),
    (CategoryKind.INCOME, "Подработка"),
    (CategoryKind.INCOME, "Подарки"),
    (CategoryKind.INCOME, "Другое"),
)


def category_key(name: str) -> str:
    """The form names are compared in: "Кафе" and " КАФЕ " are one category."""
    return name.strip().casefold()


def require_category_editor(
    *, actor_id: uuid.UUID, role: Role, created_by: uuid.UUID | None
) -> None:
    """A category is changed by its author or the owner; default ones (no author) by the owner."""
    if role is Role.OWNER or (created_by is not None and created_by == actor_id):
        return
    raise PermissionDeniedError("Only its author or the household owner can change this category")


def check_category_fits(operation: OperationType, kind: CategoryKind) -> None:
    if operation.value != kind.value:
        raise CategoryKindMismatchError(f"A {kind} category cannot be used for an {operation}")


def require_operation_editor(
    *, actor_id: uuid.UUID, role: Role, author_id: uuid.UUID | None
) -> None:
    """An operation is changed by its author or the household owner."""
    if role is Role.OWNER or (author_id is not None and author_id == actor_id):
        return
    raise PermissionDeniedError("Only its author or the household owner can change this operation")
