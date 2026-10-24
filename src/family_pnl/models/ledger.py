import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import (
    DEFAULT_CATEGORIES,
    AccountType,
    CategoryKind,
    OperationType,
    category_key,
)
from family_pnl.models.base import Base
from family_pnl.models.types import checked_enum, currency_column


class Account(Base):
    """A card, cash or savings account of a household; personal (has a holder) or shared."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    # NULL for a shared account. A personal account keeps its holder's operations visible
    # to the household even if the holder leaves, hence SET NULL rather than CASCADE.
    holder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[AccountType] = mapped_column(checked_enum(AccountType, "account_type"))
    currency: Mapped[Currency] = mapped_column(currency_column())
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Category(Base):
    """An income or expense category of a household; default ones have no author."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("household_id", "kind", "name_key", name="uq_categories_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[CategoryKind] = mapped_column(checked_enum(CategoryKind, "category_kind"))
    name: Mapped[str] = mapped_column(String(50))
    # domain.ledger.category_key(name): uniqueness is decided by the same rule as in code.
    name_key: Mapped[str] = mapped_column(String(50))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @classmethod
    def defaults_for(cls, household_id: uuid.UUID, now: datetime) -> list["Category"]:
        return [
            cls(
                id=uuid.uuid4(),
                household_id=household_id,
                kind=kind,
                name=name,
                name_key=category_key(name),
                archived=False,
                created_by=None,
                created_at=now,
            )
            for kind, name in DEFAULT_CATEGORIES
        ]


class Operation(Base):
    """An income or an expense: the original amount and currency as entered."""

    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_operations_household_date", "household_id", "operation_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    type: Mapped[OperationType] = mapped_column(checked_enum(OperationType, "operation_type"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(currency_column())
    # A calendar date in the household time zone, not a moment in time.
    operation_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"), index=True)
    comment: Mapped[str | None] = mapped_column(String(500))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
