import uuid
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.budgets import BudgetStatus
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import OperationType
from family_pnl.models import Budget, BudgetLimit, Category, Operation


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, household_id: uuid.UUID, month: date) -> Budget | None:
        return await self._session.scalar(
            select(Budget).where(Budget.household_id == household_id, Budget.month == month)
        )

    async def approved_months(self, household_id: uuid.UUID, months: list[date]) -> frozenset[date]:
        """Which of `months` have an approved budget."""
        found = await self._session.scalars(
            select(Budget.month).where(
                Budget.household_id == household_id,
                Budget.month.in_(months),
                Budget.status == BudgetStatus.APPROVED,
            )
        )
        return frozenset(found)

    def add(self, item: Budget | BudgetLimit) -> None:
        self._session.add(item)

    async def limits(self, budget_id: uuid.UUID) -> list[tuple[BudgetLimit, Category]]:
        rows = await self._session.execute(
            select(BudgetLimit, Category)
            .join(Category, Category.id == BudgetLimit.category_id)
            .where(BudgetLimit.budget_id == budget_id)
            .order_by(Category.name)
        )
        return [(row[0], row[1]) for row in rows]

    async def limit(self, budget_id: uuid.UUID, category_id: uuid.UUID) -> BudgetLimit | None:
        return await self._session.scalar(
            select(BudgetLimit).where(
                BudgetLimit.budget_id == budget_id, BudgetLimit.category_id == category_id
            )
        )

    async def delete(self, item: BudgetLimit) -> None:
        await self._session.delete(item)


class SpendingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def expenses(
        self,
        household_id: uuid.UUID,
        *,
        first_day: date,
        next_first_day: date,
        category_ids: list[uuid.UUID],
    ) -> list[tuple[uuid.UUID, Currency, date, Decimal]]:
        """Expense sums per category, currency and date within [first_day, next_first_day)."""
        rows = await self._session.execute(
            select(
                Operation.category_id,
                Operation.currency,
                Operation.operation_date,
                func.sum(Operation.amount),
            )
            .where(
                Operation.household_id == household_id,
                Operation.type == OperationType.EXPENSE,
                Operation.category_id.in_(category_ids),
                Operation.operation_date >= first_day,
                Operation.operation_date < next_first_day,
            )
            .group_by(Operation.category_id, Operation.currency, Operation.operation_date)
        )
        # Expenses always have a category: ck_operations_category_unless_transfer.
        return [(cast(uuid.UUID, row[0]), row[1], row[2], row[3]) for row in rows]
