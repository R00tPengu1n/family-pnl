import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import alembic_config


async def test_migrations_are_applied_up_to_head(
    db_session: AsyncSession, migrated_database_url: str
) -> None:
    head = ScriptDirectory.from_config(alembic_config(migrated_database_url)).get_current_head()

    version = await db_session.scalar(text("SELECT version_num FROM alembic_version"))

    assert version == head


@pytest.mark.parametrize("attempt", [1, 2])
async def test_each_test_starts_from_a_clean_database(
    db_session: AsyncSession, attempt: int
) -> None:
    # Runs twice; the second run passes only if the first run's row was rolled back.
    await db_session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": f"probe-{attempt}"}
    )
    await db_session.commit()

    count = await db_session.scalar(text("SELECT count(*) FROM alembic_version"))

    assert count == 2


def test_migrations_downgrade_to_base_and_upgrade_back(migrated_database_url: str) -> None:
    config = alembic_config(migrated_database_url)

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_alembic_config_keeps_percent_signs_in_the_url() -> None:
    url = "postgresql+asyncpg://user:p%40ss@localhost:5432/db"

    assert alembic_config(url).get_main_option("sqlalchemy.url") == url
