"""Budget execution: spending against limits, and threshold notifications (ADR-0009).

Spending of a category in a month is the sum of its expenses, each converted to the budget
currency at the rate of its own date, exactly, and rounded once. When an expense brings a
category to 80% or 100% of its limit, a notification is written to the outbox in the same
transaction; its dedupe key makes it happen once per threshold, category and month.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.domain.budgets import first_of_month, next_month, reached_thresholds
from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money
from family_pnl.repositories.budgets import BudgetRepository, SpendingRepository
from family_pnl.repositories.notifications import NotificationRepository
from family_pnl.services.auth import CurrentUser
from family_pnl.services.fx import RateService, RatesOnDate, RatesUnavailableError

logger = structlog.get_logger(__name__)

THRESHOLD_KIND = "budget_threshold"


@dataclass(frozen=True, slots=True)
class CategoryExecution:
    category_id: uuid.UUID
    category: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    percent: Decimal  # of the limit, one decimal place


@dataclass(frozen=True, slots=True)
class ExecutionView:
    month: date
    currency: Currency
    categories: list[CategoryExecution]


class BudgetExecutionService:
    def __init__(self, session: AsyncSession, rates: RateService, clock: Clock) -> None:
        self._rates = rates
        self._clock = clock
        self._budgets = BudgetRepository(session)
        self._spending = SpendingRepository(session)
        self._notifications = NotificationRepository(session)

    async def execution(self, user: CurrentUser, month: date) -> ExecutionView:
        budget = await self._budgets.get(user.household_id, month)
        if budget is None:
            return ExecutionView(month, user.household_base_currency, [])
        limits = await self._budgets.limits(budget.id)
        spent = await self._spent(
            user.household_id, month, budget.currency, [c.id for _, c in limits]
        )
        rows = []
        for limit, category in limits:
            used = spent.get(category.id, Money.zero(budget.currency)).rounded().amount
            rows.append(
                CategoryExecution(
                    category_id=category.id,
                    category=category.name,
                    limit=limit.amount,
                    spent=used,
                    remaining=limit.amount - used,
                    percent=(used * 100 / limit.amount).quantize(Decimal("0.1")),
                )
            )
        return ExecutionView(month, budget.currency, rows)

    async def check_thresholds(
        self, household_id: uuid.UUID, category_id: uuid.UUID, operation_date: date
    ) -> None:
        """Record the thresholds the category has reached; call before the commit."""
        month = first_of_month(operation_date)
        budget = await self._budgets.get(household_id, month)
        limit = None if budget is None else await self._budgets.limit(budget.id, category_id)
        if budget is None or limit is None:
            return
        try:
            spent = await self._spent(household_id, month, budget.currency, [category_id])
        except RatesUnavailableError:
            # Recording the expense matters more; the next expense checks again.
            logger.warning("budget_thresholds_skipped", category_id=str(category_id))
            return
        used = spent.get(category_id, Money.zero(budget.currency)).rounded().amount
        for threshold in reached_thresholds(used, limit.amount):
            await self._notifications.add_once(
                notification_id=uuid.uuid4(),
                household_id=household_id,
                kind=THRESHOLD_KIND,
                dedupe_key=f"{THRESHOLD_KIND}:{budget.id}:{category_id}:{threshold}",
                payload={
                    "month": month.strftime("%Y-%m"),
                    "category_id": str(category_id),
                    "threshold": threshold,
                    "spent": str(used),
                    "limit": str(limit.amount),
                    "currency": budget.currency.value,
                },
                created_at=self._clock.now(),
            )

    async def _spent(
        self,
        household_id: uuid.UUID,
        month: date,
        currency: Currency,
        category_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Money]:
        rows = await self._spending.expenses(
            household_id,
            first_day=month,
            next_first_day=next_month(month),
            category_ids=category_ids,
        )
        rates_by_date: dict[date, RatesOnDate] = {}
        totals: dict[uuid.UUID, Money] = {}
        for category_id, row_currency, day, amount in rows:
            money = Money(Decimal(amount), Currency(row_currency))
            if money.currency is not currency:
                if day not in rates_by_date:
                    rates_by_date[day] = await self._rates.rates_on(day)
                money = rates_by_date[day].convert(money, currency)
            totals[category_id] = totals.get(category_id, Money.zero(currency)) + money
        return totals
