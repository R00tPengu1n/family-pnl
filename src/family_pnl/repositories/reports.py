"""Database access for period reports. Every query is scoped to one household (ADR-0004)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import CategoryKind, OperationType
from family_pnl.models import Budget, BudgetLimit, Category, Operation


@dataclass(frozen=True, slots=True)
class ReportRow:
    """Sum of incomes or expenses for one category, author, currency and date."""

    type: OperationType
    category_id: uuid.UUID
    author_id: uuid.UUID | None
    currency: Currency
    operation_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PlannedLimit:
    month: date
    budget_currency: Currency
    category_id: uuid.UUID
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CategoryName:
    id: uuid.UUID
    name: str
    kind: CategoryKind


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(
        self, household_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[ReportRow]:
        """Incomes and expenses in [date_from, date_to]; transfers stay inside the household."""
        result = await self._session.execute(
            select(
                Operation.type,
                Operation.category_id,
                Operation.author_id,
                Operation.currency,
                Operation.operation_date,
                func.sum(Operation.amount),
            )
            .where(
                Operation.household_id == household_id,
                Operation.type.in_([OperationType.INCOME, OperationType.EXPENSE]),
                Operation.operation_date >= date_from,
                Operation.operation_date <= date_to,
            )
            .group_by(
                Operation.type,
                Operation.category_id,
                Operation.author_id,
                Operation.currency,
                Operation.operation_date,
            )
        )
        # Incomes and expenses always have a category: ck_operations_category_unless_transfer.
        return [
            ReportRow(row[0], cast(uuid.UUID, row[1]), row[2], row[3], row[4], row[5])
            for row in result
        ]

    async def limits(
        self, household_id: uuid.UUID, first_month: date, last_month: date
    ) -> list[PlannedLimit]:
        """Limits of the budgets for the months from first_month to last_month inclusive."""
        result = await self._session.execute(
            select(Budget.month, Budget.currency, BudgetLimit.category_id, BudgetLimit.amount)
            .join(BudgetLimit, BudgetLimit.budget_id == Budget.id)
            .where(
                Budget.household_id == household_id,
                Budget.month >= first_month,
                Budget.month <= last_month,
            )
        )
        return [PlannedLimit(row[0], row[1], row[2], row[3]) for row in result]

    async def categories(self, household_id: uuid.UUID) -> dict[uuid.UUID, CategoryName]:
        """All categories, archived ones too: old operations may use them."""
        result = await self._session.execute(
            select(Category.id, Category.name, Category.kind).where(
                Category.household_id == household_id
            )
        )
        return {row[0]: CategoryName(row[0], row[1], row[2]) for row in result}
