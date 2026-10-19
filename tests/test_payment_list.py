"""
Тесты списка платежей GET /payments с фильтрами.
Tests for the payment list GET /payments with filters.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.security import compute_signature


def create_payment(client: TestClient, email: str) -> str:
    body = {"tariff_id": "basic", "email": email, "method": "card"}
    return client.post("/payments", json=body).json()["id"]


def mark_succeeded(client: TestClient, payment_id: str) -> None:
    body = json.dumps({"payment_id": payment_id, "status": "succeeded"}).encode()
    signature = compute_signature(os.environ["WEBHOOK_SECRET"], body)
    headers = {"Content-Type": "application/json", "X-Signature": signature}
    assert client.post("/webhooks/bank", content=body, headers=headers).status_code == 200


@pytest.fixture
def three_payments(client: TestClient) -> dict[str, str]:
    """
    Три платежа: два от anna (один оплачен), один от boris.
    Three payments: two from anna (one paid), one from boris.
    """
    ids = {
        "anna_pending": create_payment(client, "anna@example.com"),
        "anna_paid": create_payment(client, "anna@example.com"),
        "boris_pending": create_payment(client, "boris@example.com"),
    }
    mark_succeeded(client, ids["anna_paid"])
    return ids


def ids_of(client: TestClient, params: dict[str, str | int]) -> set[str]:
    response = client.get("/payments", params=params)
    assert response.status_code == 200
    return {payment["id"] for payment in response.json()}


def test_list_without_filters_returns_all(
    client: TestClient, three_payments: dict[str, str]
) -> None:
    assert ids_of(client, {}) == set(three_payments.values())


def test_filter_by_email_is_case_insensitive(
    client: TestClient, three_payments: dict[str, str]
) -> None:
    expected = {three_payments["anna_pending"], three_payments["anna_paid"]}
    assert ids_of(client, {"email": "ANNA@example.com"}) == expected


def test_filter_by_status(client: TestClient, three_payments: dict[str, str]) -> None:
    expected = {three_payments["anna_pending"], three_payments["boris_pending"]}
    assert ids_of(client, {"status": "pending"}) == expected


def test_filter_by_email_and_status(client: TestClient, three_payments: dict[str, str]) -> None:
    params = {"email": "anna@example.com", "status": "succeeded"}
    assert ids_of(client, params) == {three_payments["anna_paid"]}


def test_filter_without_matches_returns_empty_list(
    client: TestClient, three_payments: dict[str, str]
) -> None:
    assert ids_of(client, {"email": "nobody@example.com"}) == set()


def test_limit_and_offset(client: TestClient, three_payments: dict[str, str]) -> None:
    # Две страницы по 2 платежа вместе дают все 3 платежа без повторов.
    # Two pages of 2 payments together give all 3 payments without repeats.
    first_page = client.get("/payments", params={"limit": 2}).json()
    second_page = client.get("/payments", params={"limit": 2, "offset": 2}).json()

    assert len(first_page) == 2
    assert len(second_page) == 1
    all_ids = {p["id"] for p in first_page} | {p["id"] for p in second_page}
    assert all_ids == set(three_payments.values())


@pytest.mark.parametrize(
    "params",
    [{"status": "paid"}, {"limit": 0}, {"limit": 101}, {"offset": -1}],
)
def test_invalid_list_params_return_422(client: TestClient, params: dict[str, str | int]) -> None:
    assert client.get("/payments", params=params).status_code == 422
