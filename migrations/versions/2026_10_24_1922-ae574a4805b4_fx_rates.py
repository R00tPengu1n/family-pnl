"""fx rates: official NBRB rates, BYN per unit, one row per currency and date

Revision ID: ae574a4805b4
Revises: 6b419c8f64c9
Create Date: 2026-10-24 19:22:17.646541

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae574a4805b4"
down_revision: str | Sequence[str] | None = "6b419c8f64c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column(
            "currency",
            sa.Enum(
                "RUB", "BYN", "USD", name="currency", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("byn_per_unit", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("currency", "rate_date", name=op.f("pk_fx_rates")),
    )


def downgrade() -> None:
    op.drop_table("fx_rates")
