"""transfers: operations between two accounts, with both amounts

Revision ID: d5cc61b31be5
Revises: 53563cefd10a
Create Date: 2026-10-24 22:19:38.770830

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5cc61b31be5"
down_revision: str | Sequence[str] | None = "53563cefd10a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("operations", sa.Column("target_account_id", sa.Uuid(), nullable=True))
    op.add_column("operations", sa.Column("target_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("operations", sa.Column("target_currency", sa.String(3), nullable=True))
    op.create_index(
        op.f("ix_operations_target_account_id"), "operations", ["target_account_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_operations_target_account_id_accounts"),
        "operations",
        "accounts",
        ["target_account_id"],
        ["id"],
    )
    op.alter_column("operations", "category_id", existing_type=sa.Uuid(), nullable=True)
    # "transfer" is longer than the old values; the CHECK of allowed types is replaced.
    op.drop_constraint(op.f("ck_operations_operation_type"), "operations", type_="check")
    op.alter_column(
        "operations", "type", existing_type=sa.String(7), type_=sa.String(8), nullable=False
    )
    op.create_check_constraint(
        op.f("ck_operations_operation_type"),
        "operations",
        "type IN ('income', 'expense', 'transfer')",
    )
    # Autogenerate does not detect CHECK constraints; the rest are added by hand too.
    op.create_check_constraint(
        op.f("ck_operations_target_currency"),
        "operations",
        "target_currency IN ('RUB', 'BYN', 'USD')",
    )
    op.create_check_constraint(
        op.f("ck_operations_category_unless_transfer"),
        "operations",
        "(type = 'transfer') = (category_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_operations_target_iff_transfer"),
        "operations",
        "(type = 'transfer') = (target_account_id IS NOT NULL"
        " AND target_amount IS NOT NULL AND target_currency IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_operations_target_amount_positive"), "operations", "target_amount > 0"
    )
    op.create_check_constraint(
        op.f("ck_operations_transfer_two_accounts"),
        "operations",
        "target_account_id <> account_id",
    )


def downgrade() -> None:
    # Fails while transfers exist: they have no category and would break the old schema.
    # Deliberately not deleting them; remove transfers by hand before downgrading.
    for name in (
        "transfer_two_accounts",
        "target_amount_positive",
        "target_iff_transfer",
        "category_unless_transfer",
        "target_currency",
        "operation_type",
    ):
        op.drop_constraint(op.f(f"ck_operations_{name}"), "operations", type_="check")
    op.alter_column(
        "operations", "type", existing_type=sa.String(8), type_=sa.String(7), nullable=False
    )
    op.create_check_constraint(
        op.f("ck_operations_operation_type"), "operations", "type IN ('income', 'expense')"
    )
    op.alter_column("operations", "category_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(
        op.f("fk_operations_target_account_id_accounts"), "operations", type_="foreignkey"
    )
    op.drop_index(op.f("ix_operations_target_account_id"), table_name="operations")
    op.drop_column("operations", "target_currency")
    op.drop_column("operations", "target_amount")
    op.drop_column("operations", "target_account_id")
