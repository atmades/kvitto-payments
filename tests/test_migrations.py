"""
Migration tests: each runs on its own temporary database file.
"""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.database import Base
from app.migrate import alembic_config, run_migrations


def test_migrations_match_models(tmp_path: Path) -> None:
    # If someone changes a model but forgets a migration, this test fails.
    url = f"sqlite:///{tmp_path}/migrations.db"
    run_migrations(url)

    engine = create_engine(url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert differences == []


def test_downgrade_removes_tables_and_upgrade_restores_them(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/migrations.db"
    engine = create_engine(url)

    run_migrations(url)
    assert {"tariffs", "payments"} <= set(inspect(engine).get_table_names())

    command.downgrade(alembic_config(url), "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

    run_migrations(url)
    assert {"tariffs", "payments"} <= set(inspect(engine).get_table_names())
    engine.dispose()
