"""telegram accounts and link codes

Users may now exist without email and password (Telegram only), but every user keeps at
least one way to sign in.

Revision ID: 6b419c8f64c9
Revises: 108e87a7a4ca
Create Date: 2026-10-24 18:25:49.832242

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b419c8f64c9"
down_revision: str | Sequence[str] | None = "108e87a7a4ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_link_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_telegram_link_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_link_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_telegram_link_codes_code_hash")),
    )
    op.create_index(
        op.f("ix_telegram_link_codes_user_id"), "telegram_link_codes", ["user_id"], unique=False
    )
    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=100), nullable=True))
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=320), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.create_unique_constraint(op.f("uq_users_telegram_id"), "users", ["telegram_id"])
    # Autogenerate does not detect CHECK constraints; added by hand.
    op.create_check_constraint(
        op.f("ck_users_has_login"), "users", "email IS NOT NULL OR telegram_id IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_users_email_with_password"), "users", "(email IS NULL) = (password_hash IS NULL)"
    )


def downgrade() -> None:
    # Fails while Telegram-only users exist: they would lose their only login. Deliberately
    # not deleting them here; remove such users by hand before downgrading.
    op.drop_constraint(op.f("ck_users_email_with_password"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_has_login"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_telegram_id"), "users", type_="unique")
    op.alter_column("users", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=False)
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=320), nullable=False)
    op.drop_column("users", "display_name")
    op.drop_column("users", "telegram_id")
    op.drop_index(op.f("ix_telegram_link_codes_user_id"), table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
