import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import CategoryKind
from family_pnl.services.reports import Report, Totals


class TotalsOut(BaseModel):
    income: Decimal
    expense: Decimal
    net: Decimal

    @classmethod
    def of(cls, totals: Totals) -> "TotalsOut":
        return cls(income=totals.income, expense=totals.expense, net=totals.net)


class CategoryLineOut(BaseModel):
    category_id: uuid.UUID
    category: str
    kind: CategoryKind
    amount: Decimal


class MemberLineOut(BaseModel):
    user_id: uuid.UUID | None
    name: str | None
    totals: TotalsOut


class MonthLineOut(BaseModel):
    month: str  # YYYY-MM
    totals: TotalsOut


class PlanLineOut(BaseModel):
    month: str  # YYYY-MM
    category_id: uuid.UUID
    category: str
    planned: Decimal
    actual: Decimal
    remaining: Decimal


class ReportOut(BaseModel):
    date_from: date
    date_to: date
    currency: Currency
    totals: TotalsOut
    by_category: list[CategoryLineOut]
    by_member: list[MemberLineOut]
    by_month: list[MonthLineOut]
    plan_vs_actual: list[PlanLineOut]

    @classmethod
    def of(cls, report: Report) -> "ReportOut":
        return cls(
            date_from=report.date_from,
            date_to=report.date_to,
            currency=report.currency,
            totals=TotalsOut.of(report.totals),
            by_category=[
                CategoryLineOut(
                    category_id=c.category_id, category=c.category, kind=c.kind, amount=c.amount
                )
                for c in report.by_category
            ],
            by_member=[
                MemberLineOut(user_id=m.user_id, name=m.name, totals=TotalsOut.of(m.totals))
                for m in report.by_member
            ],
            by_month=[
                MonthLineOut(month=m.month.strftime("%Y-%m"), totals=TotalsOut.of(m.totals))
                for m in report.by_month
            ],
            plan_vs_actual=[
                PlanLineOut(
                    month=p.month.strftime("%Y-%m"),
                    category_id=p.category_id,
                    category=p.category,
                    planned=p.planned,
                    actual=p.actual,
                    remaining=p.remaining,
                )
                for p in report.plan_vs_actual
            ],
        )
