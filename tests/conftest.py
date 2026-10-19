"""
Общие фикстуры для тестов. pytest находит этот файл сам.
Shared test fixtures. pytest picks this file up automatically.

Фикстура — функция, которая готовит что-то для теста (клиент, сессию)
и передаётся в тест по имени параметра.
A fixture is a function that prepares something for a test (a client,
a session) and is passed to the test by parameter name.
"""

import os
import tempfile
from collections.abc import Iterator

# Тесты работают с отдельной временной базой, а не с kvitto.db.
# Переменную нужно задать ДО импорта app: database.py читает её при импорте.
# Tests use a separate temporary database instead of kvitto.db.
# The variable must be set BEFORE importing app: database.py reads it on import.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

# Секрет для подписи вебхуков в тестах.
# The webhook signing secret used in tests.
os.environ["WEBHOOK_SECRET"] = "test-secret"

# Поэтому импорты ниже стоят после кода, а не в начале файла.
# That is why the imports below come after code, not at the top of the file.
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """
    HTTP-клиент к приложению с чистой базой для каждого теста.
    An HTTP client for the app with a clean database for every test.
    """
    # Удаляем все таблицы, чтобы тесты не влияли друг на друга.
    # Drop all tables so tests do not affect each other.
    Base.metadata.drop_all(engine)
    # with TestClient(...) запускает lifespan: таблицы и тарифы создаются заново.
    # with TestClient(...) runs lifespan: tables and tariffs are created again.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """
    Сессия базы, чтобы заглянуть в неё напрямую, например посчитать платежи.
    A database session to look into the DB directly, e.g. to count payments.
    """
    with SessionLocal() as session:
        yield session