"""notification delivery state: next attempt time and giving up

Revision ID: 3f6a1c2d9b47
Revises: 949f4fca5ac2
Create Date: 2026-10-24 23:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f6a1c2d9b47"
down_revision: str | Sequence[str] | None = "949f4fca5ac2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE notifications SET next_attempt_at = created_at")
    op.alter_column("notifications", "next_attempt_at", nullable=False)
    op.add_column(
        "notifications", sa.Column("gave_up_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_index("ix_notifications_pending", table_name="notifications")
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["next_attempt_at"],
        postgresql_where=sa.text("sent_at IS NULL AND gave_up_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_pending", table_name="notifications")
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["created_at"],
        postgresql_where=sa.text("sent_at IS NULL"),
    )
    op.drop_column("notifications", "gave_up_at")
    op.drop_column("notifications", "next_attempt_at")
