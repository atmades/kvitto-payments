"""
Models describe database tables. All amounts are in kopecks, type int.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.domain import PaymentStatus


class Tariff(Base):
    __tablename__ = "tariffs"

    # id is a short tariff name: "basic", "standard", "premium".
    # A string is clearer than a number: requests show which tariff is chosen.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer)


def new_payment_id() -> str:
    """
    A random unique payment id, e.g. "3f2b9c1e-...".
    """
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """
    Current time in UTC — the same regardless of the server's time zone.
    """
    return datetime.now(UTC)


class Payment(Base):
    __tablename__ = "payments"

    # UUID instead of 1, 2, 3: ids cannot be guessed or used to count payments.
    # default=new_payment_id: the function is called when a row is inserted.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_payment_id)
    # ForeignKey: tariff_id may only hold the id of an existing tariff.
    tariff_id: Mapped[str] = mapped_column(ForeignKey("tariffs.id"))
    email: Mapped[str] = mapped_column(String(320))
    method: Mapped[str] = mapped_column(String(20))
    # None for card and sbp, 3/6/12 for installments.
    installment_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Amount to pay and discount — in kopecks.
    amount: Mapped[int] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.PENDING)
    # The list of payments in kopecks is stored as JSON, e.g. [663334, 663333, 663333].
    schedule: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # unique=True is the main guard against duplicates: the database refuses
    # two payments with the same key. Multiple NULLs are still allowed.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)