"""
Тесты вебхука банка: переходы статусов и проверка подписи.
Bank webhook tests: status transitions and signature check.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import update

import app.main
from app.database import SessionLocal
from app.domain import PaymentStatus
from app.models import Payment
from app.security import compute_signature

# Цепочка вебхуков, которая приводит новый платёж в нужный статус.
# The chain of webhooks that brings a new payment to the given status.
PATH_TO_STATUS = {
    "pending": [],
    "succeeded": ["succeeded"],
    "failed": ["failed"],
    "refunded": ["succeeded", "refunded"],
}


def create_payment(client: TestClient) -> str:
    """
    Создаёт платёж и возвращает его id.
    Creates a payment and returns its id.
    """
    body = {"tariff_id": "basic", "email": "student@example.com", "method": "card"}
    return client.post("/payments", json=body).json()["id"]


def send_webhook(
    client: TestClient, payment_id: str, new_status: str, signature: str | bytes | None = None
) -> Response:
    """
    Отправляет вебхук. По умолчанию подписывает тело правильным секретом.
    Sends a webhook. By default the body is signed with the correct secret.
    """
    # Сериализуем сами и отправляем именно эти байты (content=, а не json=),
    # чтобы подпись точно считалась от того, что уйдёт на сервер.
    # We serialize ourselves and send exactly these bytes (content=, not json=),
    # so the signature is computed over what actually reaches the server.
    body = json.dumps({"payment_id": payment_id, "status": new_status}).encode()
    if signature is None:
        signature = compute_signature(os.environ["WEBHOOK_SECRET"], body)
    headers = {"Content-Type": "application/json", "X-Signature": signature}
    return client.post("/webhooks/bank", content=body, headers=headers)


def payment_status(client: TestClient, payment_id: str) -> str:
    return client.get(f"/payments/{payment_id}").json()["status"]


def payment_in_status(client: TestClient, target: str) -> str:
    """
    Новый платёж, доведённый вебхуками до статуса target.
    A new payment moved to the target status via webhooks.
    """
    payment_id = create_payment(client)
    for step in PATH_TO_STATUS[target]:
        assert send_webhook(client, payment_id, step).status_code == 200
    assert payment_status(client, payment_id) == target
    return payment_id


@pytest.mark.parametrize(
    ("old", "new"),
    [("pending", "succeeded"), ("pending", "failed"), ("succeeded", "refunded")],
)
def test_allowed_transition_changes_status(client: TestClient, old: str, new: str) -> None:
    payment_id = payment_in_status(client, old)

    response = send_webhook(client, payment_id, new)

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert payment_status(client, payment_id) == new


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("pending", "pending"),
        ("pending", "refunded"),
        ("succeeded", "succeeded"),
        ("succeeded", "pending"),
        ("succeeded", "failed"),
        ("failed", "succeeded"),
        ("failed", "refunded"),
        ("refunded", "succeeded"),
        ("refunded", "refunded"),
    ],
)
def test_forbidden_transition_returns_409_and_keeps_status(
    client: TestClient, old: str, new: str
) -> None:
    payment_id = payment_in_status(client, old)

    response = send_webhook(client, payment_id, new)

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    # Главное: статус в базе не изменился.
    # The key point: the status in the database did not change.
    assert payment_status(client, payment_id) == old


def test_webhook_for_missing_payment_returns_404(client: TestClient) -> None:
    response = send_webhook(client, "does-not-exist", "succeeded")

    assert response.status_code == 404


def test_webhook_with_unknown_status_returns_422(client: TestClient) -> None:
    payment_id = create_payment(client)

    response = send_webhook(client, payment_id, "paid")

    assert response.status_code == 422
    assert payment_status(client, payment_id) == "pending"


@pytest.mark.parametrize(
    "bad_signature",
    [
        "",
        "0" * 64,
        compute_signature("wrong-secret", b"{}"),
        # Не-ASCII символы: должен быть 401, а не падение сервера с 500.
        # Non-ASCII characters: must be a 401, not a server crash with a 500.
        "naïve-signature".encode(),
    ],
)
def test_bad_signature_returns_401_and_keeps_status(
    client: TestClient, bad_signature: str | bytes
) -> None:
    payment_id = create_payment(client)

    response = send_webhook(client, payment_id, "succeeded", signature=bad_signature)

    assert response.status_code == 401
    assert payment_status(client, payment_id) == "pending"


def test_missing_signature_header_returns_401(client: TestClient) -> None:
    payment_id = create_payment(client)
    body = {"payment_id": payment_id, "status": "succeeded"}

    response = client.post("/webhooks/bank", json=body)

    assert response.status_code == 401


def test_signature_of_different_body_returns_401(client: TestClient) -> None:
    # Подпись снята с вебхука «failed», а тело подменено на «succeeded».
    # The signature was taken from a "failed" webhook, but the body says "succeeded".
    payment_id = create_payment(client)
    original = json.dumps({"payment_id": payment_id, "status": "failed"}).encode()
    stolen_signature = compute_signature(os.environ["WEBHOOK_SECRET"], original)

    response = send_webhook(client, payment_id, "succeeded", signature=stolen_signature)

    assert response.status_code == 401
    assert payment_status(client, payment_id) == "pending"


def test_webhook_rejected_when_secret_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment_id = create_payment(client)
    body = json.dumps({"payment_id": payment_id, "status": "succeeded"}).encode()
    signature = compute_signature(os.environ["WEBHOOK_SECRET"], body)
    # Убираем секрет только на время этого теста.
    # Remove the secret for this test only.
    monkeypatch.delenv("WEBHOOK_SECRET")

    response = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )

    assert response.status_code == 500
    assert payment_status(client, payment_id) == "pending"


def test_parallel_status_change_is_not_overwritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Имитируем гонку: пока наш вебхук «succeeded» проверяет переход,
    # параллельный вебхук успевает перевести платёж в failed.
    # Simulate a race: while our "succeeded" webhook checks the transition,
    # a parallel webhook manages to move the payment to failed.
    payment_id = create_payment(client)
    real_can_transition = app.main.can_transition

    def can_transition_with_parallel_change(current: PaymentStatus, new: PaymentStatus) -> bool:
        allowed = real_can_transition(current, new)
        with SessionLocal() as other_session:
            other_session.execute(
                update(Payment).where(Payment.id == payment_id).values(status="failed")
            )
            other_session.commit()
        return allowed

    monkeypatch.setattr(app.main, "can_transition", can_transition_with_parallel_change)

    response = send_webhook(client, payment_id, "succeeded")

    assert response.status_code == 409
    # Победил параллельный вебхук; наш не перезаписал его результат.
    # The parallel webhook won; ours did not overwrite its result.
    assert payment_status(client, payment_id) == "failed"