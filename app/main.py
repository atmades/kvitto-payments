"""
Entry point: application setup and endpoints.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession, SessionLocal
from app.domain import (
    PaymentMethod,
    PaymentStatus,
    build_schedule,
    calculate_discount,
    can_transition,
)

from app.migrate import run_migrations
from app.models import Payment, Tariff
from app.schemas import PaymentCreate, PaymentOut, TariffOut, WebhookIn, WebhookOut
from app.security import verify_signature

# Tariffs from the task: (id, title, price in kopecks).
TARIFFS = [
    ("basic", "Basic", 990000),  # 9,900 RUB
    ("standard", "Standard", 1990000),  # 19,900 RUB
    ("premium", "Premium", 2990000),  # 29,900 RUB
]


def seed_tariffs(db: Session) -> None:
    """
    Adds the tariffs that are not in the database yet.

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
    Code before yield runs on startup, code after it runs on shutdown.
    """
    # Apply Alembic migrations: creates the tables on the first run,
    # later runs only apply new migrations.
    run_migrations()
    with SessionLocal() as db:
        seed_tariffs(db)
    yield


app = FastAPI(title="Kvitto Payments API", lifespan=lifespan)


@app.get("/tariffs", response_model=list[TariffOut])
def list_tariffs(db: DbSession) -> list[Tariff]:
    """
    List of tariffs sorted by price.
    """
    return list(db.scalars(select(Tariff).order_by(Tariff.price)))


def find_payment_by_key(db: Session, key: str) -> Payment | None:
    """
    Finds a payment by its idempotency key; None if there is none.
    """
    return db.scalar(select(Payment).where(Payment.idempotency_key == key))


# status_code=201 is the default for a new payment.
# For a repeated request with the same key we switch it to 200 via response.
@app.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    data: PaymentCreate,
    db: DbSession,
    response: Response,
    # FastAPI turns the name idempotency_key into the Idempotency-Key header.
    # max_length=255 matches the DB column size; a longer key gets a 422.
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> Payment:
    """
    Creates a payment. A retry with the same Idempotency-Key returns the same one.
    """
    # An empty or whitespace-only header counts as "no key given".
    key = (idempotency_key or "").strip() or None

    # 1. Retry: a payment with this key already exists — return it with 200.
    if key is not None:
        existing = find_payment_by_key(db, key)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return existing

    # 2. The tariff must exist.
    tariff = db.get(Tariff, data.tariff_id)
    if tariff is None:
        raise HTTPException(status_code=404, detail="Tariff not found")

    # 3. Money: all the math lives in domain.py, here we only call it.
    discount = calculate_discount(tariff.price, data.promo_code)
    amount = tariff.price - discount
    schedule = None
    if data.method == PaymentMethod.INSTALLMENT and data.installment_months is not None:
        schedule = build_schedule(amount, data.installment_months)

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
        # Race: two requests with the same key arrived at once, both passed
        # the check in step 1, but the unique index let only the first one in.
        # Roll back our insert and return the payment the first one created.
        db.rollback()
        existing = find_payment_by_key(db, key) if key is not None else None
        if existing is None:
            # The error is not about the key — do not hide it.
            raise
        response.status_code = status.HTTP_200_OK
        return existing
    return payment


@app.get("/payments", response_model=list[PaymentOut])
def list_payments(
    db: DbSession,
    email: str | None = None,
    # The PaymentStatus type makes an unknown status filter return a 422 at once.
    status: PaymentStatus | None = None,
    # Query(ge=..., le=...) bounds the values: limit from 1 to 100.
    # Without a bound a single request could dump the whole table.
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Payment]:
    """
    A list of payments filtered by email and status, newest first.
    """
    query = select(Payment)
    if email:
        # Case-insensitive comparison: Me@Example.com == me@example.com.
        query = query.where(func.lower(Payment.email) == email.strip().lower())
    if status is not None:
        query = query.where(Payment.status == status)
    # Sorting is required for pagination: without it the row order is not guaranteed,
    # and offset could skip or repeat payments.
    query = query.order_by(Payment.created_at.desc(), Payment.id).limit(limit).offset(offset)
    return list(db.scalars(query))


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: str, db: DbSession) -> Payment:
    """
    A payment by id; 404 if it does not exist.
    """
    # db.get looks a row up by its primary key.
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


def invalid_transition() -> JSONResponse:
    """
    A 409 response exactly in the task's format: {"error": "invalid_transition"}.
    """
    # HTTPException would produce {"detail": ...}, so we build the response by hand.
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "invalid_transition"},
    )


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
    The bank reports a payment status change.
    """
    payment = db.get(Payment, data.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    current = PaymentStatus(payment.status)
    if not can_transition(current, data.status):
        return invalid_transition()

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
