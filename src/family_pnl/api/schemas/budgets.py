import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from family_pnl.api.schemas.operations import Amount
from family_pnl.domain.budgets import BudgetStatus
from family_pnl.domain.currency import Currency
from family_pnl.services.budget_execution import ExecutionView
from family_pnl.services.budgets import BudgetView


class LimitIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"amount": "800.00"}]})

    amount: Amount


class LimitOut(BaseModel):
    category_id: uuid.UUID
    category: str
    amount: Decimal


class WindowOut(BaseModel):
    opens: date
    closes: date
    open: bool


class BudgetOut(BaseModel):
    month: str  # YYYY-MM
    currency: Currency
    status: BudgetStatus
    approved_at: datetime | None
    limits: list[LimitOut]
    window: WindowOut

    @classmethod
    def of(cls, view: BudgetView) -> "BudgetOut":
        return cls(
            month=view.month.strftime("%Y-%m"),
            currency=view.currency,
            status=view.status,
            approved_at=view.approved_at,
            limits=[
                LimitOut(category_id=lim.category_id, category=lim.category, amount=lim.amount)
                for lim in view.limits
            ],
            window=WindowOut(
                opens=view.window_opens, closes=view.window_closes, open=view.window_open
            ),
        )


class CategoryExecutionOut(BaseModel):
    category_id: uuid.UUID
    category: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    percent: Decimal


class ExecutionOut(BaseModel):
    month: str
    currency: Currency
    categories: list[CategoryExecutionOut]

    @classmethod
    def of(cls, view: ExecutionView) -> "ExecutionOut":
        return cls(
            month=view.month.strftime("%Y-%m"),
            currency=view.currency,
            categories=[
                CategoryExecutionOut(
                    category_id=c.category_id,
                    category=c.category,
                    limit=c.limit,
                    spent=c.spent,
                    remaining=c.remaining,
                    percent=c.percent,
                )
                for c in view.categories
            ],
        )
