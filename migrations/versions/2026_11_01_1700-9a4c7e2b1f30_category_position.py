"""category position: defaults in a fixed order, then the household's own by name

Revision ID: 9a4c7e2b1f30
Revises: 5d8b3f0c2a61
Create Date: 2026-11-01 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a4c7e2b1f30"
down_revision: str | Sequence[str] | None = "5d8b3f0c2a61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# domain.ledger.DEFAULT_CATEGORIES as of this revision; copied, not imported, so the
# migration stays the same when the code changes.
DEFAULTS = (
    ("expense", "Продукты"),
    ("expense", "Кафе и рестораны"),
    ("expense", "Транспорт"),
    ("expense", "Жильё и коммунальные"),
    ("expense", "Связь и интернет"),
    ("expense", "Здоровье"),
    ("expense", "Одежда"),
    ("expense", "Развлечения"),
    ("expense", "Подарки"),
    ("expense", "Дети"),
    ("expense", "Другое"),
    ("income", "Зарплата"),
    ("income", "Подработка"),
    ("income", "Подарки"),
    ("income", "Другое"),
)


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("position", sa.Integer(), server_default="1000", nullable=False),
    )
    update = sa.text(
        "UPDATE categories SET position = :position "
        "WHERE created_by IS NULL AND kind = :kind AND name = :name"
    )
    for position, (kind, name) in enumerate(DEFAULTS):
        op.execute(update.bindparams(position=position, kind=kind, name=name))


def downgrade() -> None:
    op.drop_column("categories", "position")
