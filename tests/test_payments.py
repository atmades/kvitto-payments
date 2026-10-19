"""
Payment endpoint tests via real HTTP requests to the app.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main
from app.models import Payment


def payment_body(**overrides: Any) -> dict[str, Any]:
    """
    A valid request body; a test can override any field.
    """
    body: dict[str, Any] = {
        "tariff_id": "standard",
        "email": "student@example.com",
        "method": "card",
    }
    body.update(overrides)
    return body


def count_payments(db: Session) -> int:
    """
    How many payments are currently in the database.
    """
    return db.scalar(select(func.count()).select_from(Payment)) or 0


def test_tariffs_list(client: TestClient) -> None:
    response = client.get("/tariffs")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "basic", "title": "Basic", "price": 990000},
        {"id": "standard", "title": "Standard", "price": 1990000},
        {"id": "premium", "title": "Premium", "price": 2990000},
    ]


def test_create_payment_without_promo(client: TestClient) -> None:
    response = client.post("/payments", json=payment_body())

    assert response.status_code == 201
    data = response.json()
    # We check the response content, not only the status code.
    assert data["amount"] == 1990000
    assert data["discount"] == 0
    assert data["status"] == "pending"
    assert data["method"] == "card"
    assert data["schedule"] is None
    assert data["installment_months"] is None
    assert set(data) == {
        "id",
        "status",
        "tariff_id",
        "amount",
        "discount",
        "method",
        "installment_months",
        "schedule",
        "email",
        "created_at",
    }


@pytest.mark.parametrize("promo", ["KVITTO10", "kvitto10", " Kvitto10 "])
def test_create_payment_with_promo(client: TestClient, promo: str) -> None:
    response = client.post("/payments", json=payment_body(promo_code=promo))

    assert response.status_code == 201
    data = response.json()
    assert data["discount"] == 199000
    assert data["amount"] == 1791000


@pytest.mark.parametrize("months", [3, 6, 12])
def test_create_installment_payment(client: TestClient, months: int) -> None:
    body = payment_body(method="installment", installment_months=months, promo_code="kvitto10")
    response = client.post("/payments", json=body)

    assert response.status_code == 201
    data = response.json()
    assert data["installment_months"] == months
    assert len(data["schedule"]) == months
    assert sum(data["schedule"]) == data["amount"] == 1791000


def test_installment_schedule_example_from_task(client: TestClient) -> None:
    body = payment_body(method="installment", installment_months=3)
    response = client.post("/payments", json=body)

    assert response.json()["schedule"] == [663334, 663333, 663333]


@pytest.mark.parametrize(
    "overrides",
    [
        {"promo_code": "UNKNOWN"},
        {"method": "cash"},
        {"method": "installment"},
        {"method": "installment", "installment_months": 5},
        {"method": "card", "installment_months": 3},
        {"email": "not-an-email"},
    ],
)
def test_invalid_payment_returns_422_and_saves_nothing(
    client: TestClient, db: Session, overrides: dict[str, Any]
) -> None:
    response = client.post("/payments", json=payment_body(**overrides))

    assert response.status_code == 422
    assert count_payments(db) == 0


def test_unknown_tariff_returns_404(client: TestClient, db: Session) -> None:
    response = client.post("/payments", json=payment_body(tariff_id="gold"))

    assert response.status_code == 404
    assert count_payments(db) == 0


def test_get_payment_returns_same_payment(client: TestClient) -> None:
    created = client.post("/payments", json=payment_body()).json()

    response = client.get(f"/payments/{created['id']}")

    assert response.status_code == 200
    # The GET response fully matches the POST one, including created_at format.
    assert response.json() == created


def test_get_missing_payment_returns_404(client: TestClient) -> None:
    response = client.get("/payments/does-not-exist")

    assert response.status_code == 404


def test_same_idempotency_key_does_not_create_duplicate(client: TestClient, db: Session) -> None:
    headers = {"Idempotency-Key": "order-42"}

    first = client.post("/payments", json=payment_body(), headers=headers)
    second = client.post("/payments", json=payment_body(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    # The key check: exactly one payment in the database.
    assert count_payments(db) == 1


def test_different_keys_create_different_payments(client: TestClient, db: Session) -> None:
    first = client.post("/payments", json=payment_body(), headers={"Idempotency-Key": "a"})
    second = client.post("/payments", json=payment_body(), headers={"Idempotency-Key": "b"})

    assert first.json()["id"] != second.json()["id"]
    assert count_payments(db) == 2


def test_requests_without_key_always_create_payments(client: TestClient, db: Session) -> None:
    client.post("/payments", json=payment_body())
    client.post("/payments", json=payment_body())

    assert count_payments(db) == 2


def test_race_between_check_and_insert_returns_existing_payment(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a race: on the second request the "key not found yet" check is
    # wrong (as if the first request had not committed yet), so the code reaches
    # the insert. Then the except IntegrityError branch must kick in.
    headers = {"Idempotency-Key": "race"}
    first = client.post("/payments", json=payment_body(), headers=headers)

    real_find = app.main.find_payment_by_key
    calls = {"count": 0}

    def find_misses_first_time(session: Session, key: str) -> Payment | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return real_find(session, key)

    # monkeypatch temporarily replaces the function for this test only.
    monkeypatch.setattr(app.main, "find_payment_by_key", find_misses_first_time)

    second = client.post("/payments", json=payment_body(), headers=headers)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert count_payments(db) == 1
