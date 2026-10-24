"""operations: incomes and expenses in their original amount and currency

Revision ID: 53563cefd10a
Revises: 2245225870e3
Create Date: 2026-10-24 20:09:39.803300

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53563cefd10a"
down_revision: str | Sequence[str] | None = "2245225870e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "income",
                "expense",
                name="operation_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.Enum(
                "RUB", "BYN", "USD", name="currency", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("operation_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_operations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_operations_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_operations_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_operations_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_operations_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
    )
    op.create_index(op.f("ix_operations_account_id"), "operations", ["account_id"], unique=False)
    op.create_index(op.f("ix_operations_category_id"), "operations", ["category_id"], unique=False)
    op.create_index(
        "ix_operations_household_date",
        "operations",
        ["household_id", "operation_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_operations_household_date", table_name="operations")
    op.drop_index(op.f("ix_operations_category_id"), table_name="operations")
    op.drop_index(op.f("ix_operations_account_id"), table_name="operations")
    op.drop_table("operations")
