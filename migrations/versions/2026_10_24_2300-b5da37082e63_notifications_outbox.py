"""notifications outbox: events written with their cause, sent by the worker

Revision ID: b5da37082e63
Revises: 9ce2f63cffe3
Create Date: 2026-10-24 23:00:26.216535

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b5da37082e63"
down_revision: str | Sequence[str] | None = "9ce2f63cffe3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_notifications_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_dedupe_key")),
    )
    op.create_index(
        op.f("ix_notifications_household_id"), "notifications", ["household_id"], unique=False
    )
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_pending",
        table_name="notifications",
        postgresql_where=sa.text("sent_at IS NULL"),
    )
    op.drop_index(op.f("ix_notifications_household_id"), table_name="notifications")
    op.drop_table("notifications")
