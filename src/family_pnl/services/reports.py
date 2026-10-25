"""Period reports in the requester's display currency.

Every income and expense is converted to the display currency at the rate of its own date,
exactly; each figure of the report is rounded once at the end. Transfers move money inside
the household and are not part of a report.

Plan vs actual covers every budget month that overlaps the period. The actual side counts
the expenses inside the period only, so a period that cuts a month shows part of it. A
limit is set in the budget currency and is converted at the rate of the first day of its
month, or of today for a month that has not started yet.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import ValidationFailedError
from family_pnl.domain.budgets import first_of_month, local_today
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import CategoryKind, OperationType
from family_pnl.domain.money import Money
from family_pnl.repositories.identity import HouseholdRepository
from family_pnl.repositories.reports import CategoryName, ReportRepository, ReportRow
from family_pnl.services.auth import CurrentUser
from family_pnl.services.fx import RateService, RatesOnDate

MAX_PERIOD = timedelta(days=366)


class InvalidPeriodError(ValidationFailedError):
    code = "invalid_period"


@dataclass(frozen=True, slots=True)
class Totals:
    income: Decimal
    expense: Decimal
    net: Decimal


@dataclass(frozen=True, slots=True)
class CategoryLine:
    category_id: uuid.UUID
    category: str
    kind: CategoryKind
    amount: Decimal


@dataclass(frozen=True, slots=True)
class MemberLine:
    user_id: uuid.UUID | None
    name: str | None
    totals: Totals


@dataclass(frozen=True, slots=True)
class MonthLine:
    month: date
    totals: Totals


@dataclass(frozen=True, slots=True)
class PlanLine:
    month: date
    category_id: uuid.UUID
    category: str
    planned: Decimal
    actual: Decimal
    remaining: Decimal


@dataclass(frozen=True, slots=True)
class Report:
    date_from: date
    date_to: date
    currency: Currency
    totals: Totals
    by_category: list[CategoryLine]
    by_member: list[MemberLine]
    by_month: list[MonthLine]
    plan_vs_actual: list[PlanLine]


@dataclass(slots=True)
class _Sums:
    currency: Currency
    income: Money = field(init=False)
    expense: Money = field(init=False)

    def __post_init__(self) -> None:
        self.income = Money.zero(self.currency)
        self.expense = Money.zero(self.currency)

    def add(self, kind: OperationType, money: Money) -> None:
        if kind is OperationType.INCOME:
            self.income = self.income + money
        else:
            self.expense = self.expense + money

    def totals(self) -> Totals:
        income, expense = self.income.rounded().amount, self.expense.rounded().amount
        return Totals(income=income, expense=expense, net=income - expense)


class ReportService:
    def __init__(self, session: AsyncSession, rates: RateService, clock: Clock) -> None:
        self._rates = rates
        self._clock = clock
        self._reports = ReportRepository(session)
        self._households = HouseholdRepository(session)

    async def report(self, user: CurrentUser, date_from: date, date_to: date) -> Report:
        if date_to < date_from:
            raise InvalidPeriodError("The period ends before it starts")
        if date_to - date_from >= MAX_PERIOD:
            raise InvalidPeriodError("A report covers at most 366 days")
        target = user.display_currency
        rates = _RateCache(self._rates)
        categories = await self._reports.categories(user.household_id)
        sums = _Aggregate(target)
        for row in await self._reports.rows(user.household_id, date_from, date_to):
            sums.add(
                row,
                await rates.convert(Money(row.amount, row.currency), target, row.operation_date),
            )
        return Report(
            date_from=date_from,
            date_to=date_to,
            currency=target,
            totals=sums.total.totals(),
            by_category=sums.category_lines(categories),
            by_member=await self._member_lines(user, sums.by_member),
            by_month=[MonthLine(m, sums.by_month[m].totals()) for m in sorted(sums.by_month)],
            plan_vs_actual=await self._plan_vs_actual(
                user, date_from, date_to, rates, sums, categories
            ),
        )

    async def _member_lines(
        self, user: CurrentUser, by_member: dict[uuid.UUID | None, _Sums]
    ) -> list[MemberLine]:
        """Members in the order they joined; authors no longer in the household last."""
        members = await self._households.list_members(user.household_id)
        order: dict[uuid.UUID | None, int] = {u.id: i for i, (_, u) in enumerate(members)}
        names: dict[uuid.UUID | None, str | None] = {
            u.id: u.display_name or u.email for _, u in members
        }
        return [
            MemberLine(author, names.get(author), sums.totals())
            for author, sums in sorted(
                by_member.items(), key=lambda item: order.get(item[0], len(order))
            )
        ]

    async def _plan_vs_actual(
        self,
        user: CurrentUser,
        date_from: date,
        date_to: date,
        rates: "_RateCache",
        sums: "_Aggregate",
        categories: dict[uuid.UUID, CategoryName],
    ) -> list[PlanLine]:
        today = local_today(self._clock.now(), ZoneInfo(user.household_timezone))
        limits = await self._reports.limits(
            user.household_id, first_of_month(date_from), first_of_month(date_to)
        )
        plan = []
        for limit in limits:
            planned = await rates.convert(
                Money(limit.amount, limit.budget_currency), sums.currency, min(limit.month, today)
            )
            actual = sums.spent.get((limit.month, limit.category_id), Money.zero(sums.currency))
            planned_amount, actual_amount = planned.rounded().amount, actual.rounded().amount
            plan.append(
                PlanLine(
                    month=limit.month,
                    category_id=limit.category_id,
                    category=categories[limit.category_id].name,
                    planned=planned_amount,
                    actual=actual_amount,
                    remaining=planned_amount - actual_amount,
                )
            )
        return sorted(plan, key=lambda line: (line.month, line.category))


@dataclass(slots=True)
class _Aggregate:
    """Every figure of a report, summed exactly in the display currency."""

    currency: Currency
    total: _Sums = field(init=False)
    by_category: dict[uuid.UUID, Money] = field(default_factory=dict)
    by_member: dict[uuid.UUID | None, _Sums] = field(default_factory=dict)
    by_month: dict[date, _Sums] = field(default_factory=dict)
    spent: dict[tuple[date, uuid.UUID], Money] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.total = _Sums(self.currency)

    def add(self, row: ReportRow, money: Money) -> None:
        month = first_of_month(row.operation_date)
        zero = Money.zero(self.currency)
        self.total.add(row.type, money)
        self.by_category[row.category_id] = self.by_category.get(row.category_id, zero) + money
        self.by_member.setdefault(row.author_id, _Sums(self.currency)).add(row.type, money)
        self.by_month.setdefault(month, _Sums(self.currency)).add(row.type, money)
        if row.type is OperationType.EXPENSE:
            key = (month, row.category_id)
            self.spent[key] = self.spent.get(key, zero) + money

    def category_lines(self, categories: dict[uuid.UUID, CategoryName]) -> list[CategoryLine]:
        """Incomes first, then expenses, each from the largest amount."""
        lines = [
            CategoryLine(c, categories[c].name, categories[c].kind, amount.rounded().amount)
            for c, amount in self.by_category.items()
        ]
        return sorted(lines, key=lambda line: (line.kind is not CategoryKind.INCOME, -line.amount))


class _RateCache:
    """One rate lookup per date for the whole report."""

    def __init__(self, rates: RateService) -> None:
        self._rates = rates
        self._by_date: dict[date, RatesOnDate] = {}

    async def convert(self, money: Money, target: Currency, day: date) -> Money:
        if money.currency is target:
            return money
        if day not in self._by_date:
            self._by_date[day] = await self._rates.rates_on(day)
        return self._by_date[day].convert(money, target)
