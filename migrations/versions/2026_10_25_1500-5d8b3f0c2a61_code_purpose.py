"""code purpose: one-time codes also give Telegram users an email and password

Revision ID: 5d8b3f0c2a61
Revises: 7c2e9a41d5b8
Create Date: 2026-10-25 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d8b3f0c2a61"
down_revision: str | Sequence[str] | None = "7c2e9a41d5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_link_codes",
        sa.Column(
            "purpose",
            sa.Enum(
                "telegram",
                "credentials",
                name="code_purpose",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="telegram",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("telegram_link_codes", "purpose")
