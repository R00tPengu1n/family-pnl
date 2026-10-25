"""Monthly budgets: limits per expense category, the approval window and approval."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.config import Settings
from family_pnl.core.errors import NotFoundError
from family_pnl.domain.budgets import (
    ApprovalWindow,
    BudgetStatus,
    approval_missed,
    local_today,
    require_budget_approver,
    require_budget_editor,
)
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import ArchivedError, OperationType, check_category_fits
from family_pnl.domain.money import CENT
from family_pnl.models import Budget, BudgetLimit
from family_pnl.repositories.budgets import BudgetRepository
from family_pnl.repositories.ledger import CategoryRepository
from family_pnl.services.auth import CurrentUser


class BudgetNotFoundError(NotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class LimitView:
    category_id: uuid.UUID
    category: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class BudgetView:
    month: date
    currency: Currency
    status: BudgetStatus
    approved_at: datetime | None
    limits: list[LimitView]
    window_opens: date
    window_closes: date
    window_open: bool
    approval_missed: bool  # the window closed without approval


class BudgetService:
    def __init__(self, session: AsyncSession, clock: Clock, settings: Settings) -> None:
        self._session = session
        self._clock = clock
        self._window = ApprovalWindow(
            start_day=settings.budget_window_start_day, end_day=settings.budget_window_end_day
        )
        self._budgets = BudgetRepository(session)
        self._categories = CategoryRepository(session)

    async def view(self, user: CurrentUser, month: date) -> BudgetView:
        """The month's budget; a month nobody has planned reads as an empty draft."""
        budget = await self._budgets.get(user.household_id, month)
        limits = [] if budget is None else await self._budgets.limits(budget.id)
        opens, closes = self._window.bounds(month)
        status = BudgetStatus.DRAFT if budget is None else budget.status
        today = self._today(user)
        return BudgetView(
            month=month,
            currency=user.household_base_currency if budget is None else budget.currency,
            status=status,
            approved_at=None if budget is None else budget.approved_at,
            limits=[LimitView(c.id, c.name, lim.amount) for lim, c in limits],
            window_opens=opens,
            window_closes=closes,
            window_open=self._window.is_open(today, month),
            approval_missed=approval_missed(status=status, today=today, window_closes=closes),
        )

    async def set_limit(
        self, user: CurrentUser, month: date, category_id: uuid.UUID, amount: Decimal
    ) -> BudgetView:
        budget = await self._editable(user, month)
        category = await self._categories.get(user.household_id, category_id)
        if category is None:
            raise NotFoundError("Category not found")
        if category.archived:
            raise ArchivedError("The category is archived")
        check_category_fits(OperationType.EXPENSE, category.kind)
        if budget is None:
            budget = self._new_budget(user, month)
            self._budgets.add(budget)
            await self._session.flush()  # the limit references the budget row
        limit = await self._budgets.limit(budget.id, category.id)
        if limit is None:
            self._budgets.add(
                BudgetLimit(
                    id=uuid.uuid4(),
                    budget_id=budget.id,
                    category_id=category.id,
                    amount=amount.quantize(CENT),
                )
            )
        else:
            limit.amount = amount.quantize(CENT)
        budget.updated_at = self._clock.now()
        await self._session.commit()
        return await self.view(user, month)

    async def remove_limit(self, user: CurrentUser, month: date, category_id: uuid.UUID) -> None:
        budget = await self._editable(user, month)
        limit = None if budget is None else await self._budgets.limit(budget.id, category_id)
        if budget is None or limit is None:
            raise NotFoundError("Limit not found")
        await self._budgets.delete(limit)
        budget.updated_at = self._clock.now()
        await self._session.commit()

    async def approve(self, user: CurrentUser, month: date) -> BudgetView:
        require_budget_approver(user.role)
        budget = await self._budgets.get(user.household_id, month)
        if budget is None:
            raise BudgetNotFoundError("There is no budget for this month yet")
        if budget.status is not BudgetStatus.APPROVED:
            now = self._clock.now()
            budget.status = BudgetStatus.APPROVED
            budget.approved_at = now
            budget.approved_by = user.id
            budget.updated_at = now
            await self._session.commit()
        return await self.view(user, month)

    async def _editable(self, user: CurrentUser, month: date) -> Budget | None:
        budget = await self._budgets.get(user.household_id, month)
        require_budget_editor(
            role=user.role,
            status=BudgetStatus.DRAFT if budget is None else budget.status,
            today=self._today(user),
            budget_month=month,
            window=self._window,
        )
        return budget

    def _new_budget(self, user: CurrentUser, month: date) -> Budget:
        now = self._clock.now()
        return Budget(
            id=uuid.uuid4(),
            household_id=user.household_id,
            month=month,
            currency=user.household_base_currency,
            status=BudgetStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )

    def _today(self, user: CurrentUser) -> date:
        return local_today(self._clock.now(), ZoneInfo(user.household_timezone))
