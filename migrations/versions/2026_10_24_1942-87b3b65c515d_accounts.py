"""accounts: personal (with a holder) or shared, one currency each

Revision ID: 87b3b65c515d
Revises: ae574a4805b4
Create Date: 2026-10-24 19:42:24.814777

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "87b3b65c515d"
down_revision: str | Sequence[str] | None = "ae574a4805b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("holder_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "card",
                "cash",
                "savings",
                name="account_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.Enum(
                "RUB", "BYN", "USD", name="currency", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_accounts_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["holder_id"],
            ["users.id"],
            name=op.f("fk_accounts_holder_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_accounts_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    op.create_index(op.f("ix_accounts_household_id"), "accounts", ["household_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_accounts_household_id"), table_name="accounts")
    op.drop_table("accounts")
