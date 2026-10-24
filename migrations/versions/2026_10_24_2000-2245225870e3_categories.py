"""categories, with the default set added to every existing household

Revision ID: 2245225870e3
Revises: 87b3b65c515d
Create Date: 2026-10-24 20:00:01.188068

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

DEFAULTS = (
    ("expense", "Продукты"),
    ("expense", "Кафе и рестораны"),
    ("expense", "Транспорт"),
    ("expense", "Жильё и коммунальные"),
    ("expense", "Связь и интернет"),
    ("expense", "Здоровье"),
    ("expense", "Одежда"),
    ("expense", "Дети"),
    ("expense", "Развлечения"),
    ("expense", "Подарки"),
    ("expense", "Другое"),
    ("income", "Зарплата"),
    ("income", "Подработка"),
    ("income", "Подарки"),
    ("income", "Другое"),
)

# revision identifiers, used by Alembic.
revision: str = "2245225870e3"
down_revision: str | Sequence[str] | None = "87b3b65c515d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "income", "expense", name="category_kind", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("name_key", sa.String(length=50), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_categories_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_categories_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("household_id", "kind", "name_key", name="uq_categories_name"),
    )
    op.create_index(
        op.f("ix_categories_household_id"), "categories", ["household_id"], unique=False
    )

    # Households created before this revision get the default set. A snapshot of the list at
    # this revision, deliberately not imported from the application code.
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("name", sa.String()),
        sa.column("name_key", sa.String()),
        sa.column("archived", sa.Boolean()),
        sa.column("created_by", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    households = op.get_bind().execute(sa.text("SELECT id FROM households")).scalars().all()
    rows = [
        {
            "id": uuid.uuid4(),
            "household_id": household_id,
            "kind": kind,
            "name": name,
            "name_key": name.strip().casefold(),
            "archived": False,
            "created_by": None,
            "created_at": now,
        }
        for household_id in households
        for kind, name in DEFAULTS
    ]
    if rows:
        op.bulk_insert(categories, rows)


def downgrade() -> None:
    op.drop_index(op.f("ix_categories_household_id"), table_name="categories")
    op.drop_table("categories")
