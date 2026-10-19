"""
Alembic environment: where to get the database URL and which models to compare with.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# Importing models registers the tables in Base.metadata; without it autogenerate sees nothing.
import app.models  # noqa: F401
from app.database import DATABASE_URL, Base

config = context.config

# Logging from alembic.ini is configured only when run from the command line.
# When migrations run from the app there is no config file, so uvicorn logging stays untouched.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The URL can be passed explicitly (tests do this); otherwise the app's DATABASE_URL is used.
url = config.get_main_option("sqlalchemy.url") or DATABASE_URL


def run_migrations() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot do most ALTER TABLE operations; batch mode recreates the table instead.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
