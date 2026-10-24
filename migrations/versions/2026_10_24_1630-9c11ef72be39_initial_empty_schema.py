"""initial empty schema

Baseline revision: the schema starts empty and each module adds its tables.

Revision ID: 9c11ef72be39
Revises:
Create Date: 2026-10-24 16:30:13.972737

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9c11ef72be39"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
