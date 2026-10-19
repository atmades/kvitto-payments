"""
Точка входа: создание приложения и эндпоинты.
Entry point: application setup and endpoints.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, DbSession, SessionLocal, engine
from app.domain import (
    PaymentMethod,
    PaymentStatus,
    build_schedule,
    calculate_discount,
    can_transition,
)
from app.models import Payment, Tariff
from app.schemas import PaymentCreate, PaymentOut, TariffOut, WebhookIn, WebhookOut
from app.security import verify_signature

# Тарифы из задания: (id, название, цена в копейках).
# Tariffs from the task: (id, title, price in kopecks).
TARIFFS = [
    ("basic", "Basic", 990000),  # 9,900 RUB
    ("standard", "Standard", 1990000),  # 19,900 RUB
    ("premium", "Premium", 2990000),  # 29,900 RUB
]


def seed_tariffs(db: Session) -> None:
    """
    Добавляет тарифы, которых ещё нет в базе.
    Adds the tariffs that are not in the database yet.

    Проверяем каждый тариф отдельно, поэтому при повторном запуске
    дубликатов не будет.
    Each tariff is checked separately, so restarting the app
    never creates duplicates.
    """
    for tariff_id, title, price in TARIFFS:
        if db.get(Tariff, tariff_id) is None:
            db.add(Tariff(id=tariff_id, title=title, price=price))
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Код до yield выполняется при старте приложения, после — при остановке.
    Code before yield runs on startup, code after it runs on shutdown.
    """
    # создать таблицы, если их ещё нет
    # create tables if they do not exist yet
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_tariffs(db)
    yield


app = FastAPI(title="Kvitto Payments API", lifespan=lifespan)


@app.get("/tariffs", response_model=list[TariffOut])
def list_tariffs(db: DbSession) -> list[Tariff]:
    """
    Список тарифов, отсортированный по цене.
    List of tariffs sorted by price.
    """
    return list(db.scalars(select(Tariff).order_by(Tariff.price)))


def find_payment_by_key(db: Session, key: str) -> Payment | None:
    """
    Ищет платёж по ключу идемпотентности; None, если такого нет.
    Finds a payment by its idempotency key; None if there is none.
    """
    return db.scalar(select(Payment).where(Payment.idempotency_key == key))


# status_code=201 — код по умолчанию для нового платежа.
# Для повторного запроса с тем же ключом поменяем его на 200 через response.
# status_code=201 is the default for a new payment.
# For a repeated request with the same key we switch it to 200 via response.
@app.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    data: PaymentCreate,
    db: DbSession,
    response: Response,
    # FastAPI сам превращает имя idempotency_key в заголовок Idempotency-Key.
    # max_length=255 совпадает с размером колонки в базе; длиннее — ответ 422.
    # FastAPI turns the name idempotency_key into the Idempotency-Key header.
    # max_length=255 matches the DB column size; a longer key gets a 422.
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> Payment:
    """
    Создаёт платёж. Повтор с тем же Idempotency-Key возвращает тот же платёж.
    Creates a payment. A retry with the same Idempotency-Key returns the same one.
    """
    # Пустой заголовок или одни пробелы считаем «ключ не передан».
    # An empty or whitespace-only header counts as "no key given".
    key = (idempotency_key or "").strip() or None

    # 1. Повторный запрос: платёж с этим ключом уже есть — отдаём его с кодом 200.
    # 1. Retry: a payment with this key already exists — return it with 200.
    if key is not None:
        existing = find_payment_by_key(db, key)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return existing

    # 2. Тариф должен существовать.
    # 2. The tariff must exist.
    tariff = db.get(Tariff, data.tariff_id)
    if tariff is None:
        raise HTTPException(status_code=404, detail="Tariff not found")

    # 3. Деньги: вся математика живёт в domain.py, здесь только вызовы.
    # 3. Money: all the math lives in domain.py, here we only call it.
    discount = calculate_discount(tariff.price, data.promo_code)
    amount = tariff.price - discount
    schedule = None
    if data.method == PaymentMethod.INSTALLMENT and data.installment_months is not None:
        schedule = build_schedule(amount, data.installment_months)

    # 4. Сохраняем. status, id и created_at заполнятся значениями по умолчанию.
    # 4. Save. status, id and created_at are filled with their defaults.
    payment = Payment(
        tariff_id=tariff.id,
        email=data.email,
        method=data.method,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        schedule=schedule,
        idempotency_key=key,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Гонка: два запроса с одним ключом пришли одновременно, оба прошли
        # проверку в шаге 1, но уникальный индекс пропустил только первый.
        # Отменяем свою вставку и отдаём платёж, который успел создать первый.
        # Race: two requests with the same key arrived at once, both passed
        # the check in step 1, but the unique index let only the first one in.
        # Roll back our insert and return the payment the first one created.
        db.rollback()
        existing = find_payment_by_key(db, key) if key is not None else None
        if existing is None:
            # Ошибка не про ключ — не прячем её, пусть будет видна.
            # The error is not about the key — do not hide it.
            raise
        response.status_code = status.HTTP_200_OK
        return existing
    return payment


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: str, db: DbSession) -> Payment:
    """
    Платёж по id; 404, если его нет.
    A payment by id; 404 if it does not exist.
    """
    # db.get ищет строку по первичному ключу.
    # db.get looks a row up by its primary key.
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


def invalid_transition() -> JSONResponse:
    """
    Ответ 409 ровно в формате из задания: {"error": "invalid_transition"}.
    A 409 response exactly in the task's format: {"error": "invalid_transition"}.
    """
    # HTTPException дал бы {"detail": ...}, поэтому собираем ответ вручную.
    # HTTPException would produce {"detail": ...}, so we build the response by hand.
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "invalid_transition"},
    )


# dependencies=[Depends(verify_signature)]: подпись проверяется до того,
# как выполнится код эндпоинта. Неверная подпись — 401, и дальше запрос не идёт.
# dependencies=[Depends(verify_signature)]: the signature is checked before
# the endpoint code runs. A bad signature gets a 401 and goes no further.
@app.post(
    "/webhooks/bank",
    response_model=WebhookOut,
    dependencies=[Depends(verify_signature)],
    responses={409: {"description": "Forbidden status transition"}},
)
def bank_webhook(data: WebhookIn, db: DbSession) -> WebhookOut | JSONResponse:
    """
    Банк сообщает о смене статуса платежа.
    The bank reports a payment status change.
    """
    payment = db.get(Payment, data.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    current = PaymentStatus(payment.status)
    if not can_transition(current, data.status):
        return invalid_transition()

    # Обновляем статус, только если он всё ещё тот, что мы прочитали.
    # Если параллельный вебхук успел его поменять, условие не совпадёт,
    # rowcount будет 0, и мы ничего не перезапишем.
    # Update the status only if it is still the one we read.
    # If a parallel webhook already changed it, the condition will not match,
    # rowcount will be 0, and we overwrite nothing.
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == current)
        .values(status=data.status)
    )
    if result.rowcount == 0:
        db.rollback()
        return invalid_transition()
    db.commit()
    return WebhookOut(result="ok")