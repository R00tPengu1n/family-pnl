"""notification recipients delivered: retries skip members who already got it

Revision ID: 7c2e9a41d5b8
Revises: 3f6a1c2d9b47
Create Date: 2026-10-25 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7c2e9a41d5b8"
down_revision: str | Sequence[str] | None = "3f6a1c2d9b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column(
            "delivered_to",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("notifications", "delivered_to")
