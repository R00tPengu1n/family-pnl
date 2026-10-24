"""member currency preferences: display and default input currency

Revision ID: 949f4fca5ac2
Revises: b5da37082e63
Create Date: 2026-10-24 23:08:34.380553

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "949f4fca5ac2"
down_revision: str | Sequence[str] | None = "b5da37082e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "display_currency",
            sa.Enum(
                "RUB",
                "BYN",
                "USD",
                name="display_currency",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "input_currency",
            sa.Enum(
                "RUB",
                "BYN",
                "USD",
                name="input_currency",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "input_currency")
    op.drop_column("users", "display_currency")
