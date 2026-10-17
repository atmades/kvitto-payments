"""
Database connection.

Three things live here:
- engine — the connection to the SQLite database file;
- SessionLocal — a session factory (a session is one conversation with the DB);
- get_db — a FastAPI dependency that provides a session for a single request.
"""

import os
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# The database URL comes from an environment variable; if it is not set,
# we use the kvitto.db file in the project folder. Tests override this
# variable and work with their own separate database.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kvitto.db")

# check_same_thread=False is needed for SQLite only: FastAPI runs regular
# (non-async) endpoints in different threads, which SQLite forbids by default.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# expire_on_commit=False: objects stay usable after commit(),
# so we can return them in a response without querying the DB again.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """
    Base class for all models (tables).
    """


def get_db() -> Iterator[Session]:
    """
    Opens a session for one request and always closes it afterwards.

    yield hands the session to the endpoint; the code after yield runs
    when the request ends, even if an error was raised.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Shorthand for endpoints: "the db parameter is a session provided by get_db".
# We write db: DbSession instead of db: Session = Depends(get_db) everywhere.
DbSession = Annotated[Session, Depends(get_db)]