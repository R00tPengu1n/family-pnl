import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.models import Budget, BudgetLimit, Category


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, household_id: uuid.UUID, month: date) -> Budget | None:
        return await self._session.scalar(
            select(Budget).where(Budget.household_id == household_id, Budget.month == month)
        )

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
