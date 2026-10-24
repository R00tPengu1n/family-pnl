import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from family_pnl.domain.budgets import BudgetStatus
from family_pnl.domain.currency import Currency
from family_pnl.models.base import Base
from family_pnl.models.types import checked_enum, currency_column


class Budget(Base):
    """Monthly limits of a household, in its base currency at the time of creation."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("household_id", "month", name="uq_budgets_month"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="month_is_first_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    month: Mapped[date] = mapped_column(Date)  # the first day of the month
    currency: Mapped[Currency] = mapped_column(currency_column())
    status: Mapped[BudgetStatus] = mapped_column(checked_enum(BudgetStatus, "budget_status"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BudgetLimit(Base):
    __tablename__ = "budget_limits"
    __table_args__ = (
        UniqueConstraint("budget_id", "category_id", name="uq_budget_limits_category"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
