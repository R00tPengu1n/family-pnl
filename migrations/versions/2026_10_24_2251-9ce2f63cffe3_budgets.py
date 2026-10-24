"""budgets and limits; households get a base currency (RUB)

Revision ID: 9ce2f63cffe3
Revises: d5cc61b31be5
Create Date: 2026-10-24 22:51:55.019030

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ce2f63cffe3"
down_revision: str | Sequence[str] | None = "d5cc61b31be5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column(
            "currency",
            sa.Enum(
                "RUB", "BYN", "USD", name="currency", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "approved", name="budget_status", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM month) = 1", name=op.f("ck_budgets_month_is_first_day")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_budgets_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_budgets_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint("household_id", "month", name="uq_budgets_month"),
    )
    op.create_table(
        "budget_limits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_budget_limits_amount_positive")),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            name=op.f("fk_budget_limits_budget_id_budgets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_budget_limits_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_limits")),
        sa.UniqueConstraint("budget_id", "category_id", name="uq_budget_limits_category"),
    )
    op.create_index(
        op.f("ix_budget_limits_budget_id"), "budget_limits", ["budget_id"], unique=False
    )
    op.add_column(
        "households",
        sa.Column(
            "base_currency",
            sa.Enum(
                "RUB", "BYN", "USD", name="base_currency", native_enum=False, create_constraint=True
            ),
            server_default="RUB",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("households", "base_currency")
    op.drop_index(op.f("ix_budget_limits_budget_id"), table_name="budget_limits")
    op.drop_table("budget_limits")
    op.drop_table("budgets")
