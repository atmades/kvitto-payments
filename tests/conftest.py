"""
Shared test fixtures. pytest picks this file up automatically.

A fixture is a function that prepares something for a test (a client,
a session) and is passed to the test by parameter name.
"""

import os
import tempfile
from collections.abc import Iterator

# Tests use a separate temporary database instead of kvitto.db.
# The variable must be set BEFORE importing app: database.py reads it on import.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

# The webhook signing secret used in tests.
os.environ["WEBHOOK_SECRET"] = "test-secret"

# That is why the imports below come after code, not at the top of the file.
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """
    An HTTP client for the app with a clean database for every test.
    """
    # Drop all tables so tests do not affect each other. alembic_version is dropped too,
    # otherwise Alembic would think the migrations are already applied and skip them.
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    # with TestClient(...) runs lifespan: migrations recreate the tables, tariffs are seeded.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """
    A database session to look into the DB directly, e.g. to count payments.
    """
    with SessionLocal() as session:
        yield session
