"""
Running Alembic migrations from code: on app startup and in tests.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

# The migrations folder sits next to the app package, in the project root.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    """
    Alembic config without alembic.ini. Without a URL, migrations/env.py uses DATABASE_URL.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations(database_url: str | None = None) -> None:
    """
    Brings the database schema up to the latest migration ("head").

    Already applied migrations are skipped, so it is safe to call on every startup.
    """
    command.upgrade(alembic_config(database_url), "head")
