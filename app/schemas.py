"""
Pydantic schemas describe what the API accepts and returns.

A model (models.py) describes a database table, while a schema describes
the JSON in a request or response. They differ on purpose: not everything
in the DB should be exposed, and not every input is stored as is.
"""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.domain import (
    INSTALLMENT_MONTHS,
    PROMO_CODES,
    PaymentMethod,
    PaymentStatus,
    normalize_promo_code,
)


class TariffOut(BaseModel):
    # from_attributes=True lets the schema be built from an SQLAlchemy object
    # (it reads tariff.id, tariff.title, tariff.price).
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    # in kopecks
    price: int


class PaymentCreate(BaseModel):
    """
    Request body of POST /payments. Anything that fails validation gets a 422.
    """

    tariff_id: str
    # EmailStr checks that the value looks like an email (needs email-validator).
    email: EmailStr
    method: PaymentMethod
    installment_months: int | None = None
    promo_code: str | None = None

    # field_validator checks a single field. The returned value replaces
    # the original one: further code receives a normalized promo code.
    @field_validator("promo_code")
    @classmethod
    def check_promo_code(cls, value: str | None) -> str | None:
        code = normalize_promo_code(value)
        if code is not None and code not in PROMO_CODES:
            # Pydantic turns a ValueError inside a validator into a 422 response.
            raise ValueError("unknown promo code")
        return code

    # model_validator(mode="after") runs after all fields are validated,
    # so it can compare fields with each other.
    @model_validator(mode="after")
    def check_installment_months(self) -> Self:
        if self.method == PaymentMethod.INSTALLMENT:
            if self.installment_months not in INSTALLMENT_MONTHS:
                raise ValueError("installment_months must be 3, 6 or 12 for installment")
        elif self.installment_months is not None:
            # An installment term makes no sense for card or SBP — an explicit
            # error is better than silently dropping the field.
            raise ValueError("installment_months is allowed only for installment")
        return self


class PaymentOut(BaseModel):
    """
    A payment in API responses — exactly the fields listed in the task.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PaymentStatus
    tariff_id: str
    # in kopecks, discount already applied
    amount: int
    # in kopecks
    discount: int
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None
    email: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        # SQLite does not store time zones: datetimes read from the DB come back
        # "naive" (without +00:00). We always write UTC, so we attach the zone
        # back — otherwise POST and GET would return different formats.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value



class WebhookIn(BaseModel):
    """
    Тело вебхука от банка. Неизвестный статус — ответ 422.
    Bank webhook body. An unknown status gets a 422.
    """

    payment_id: str
    status: PaymentStatus


class WebhookOut(BaseModel):
    """
    Ответ на успешный вебхук: {"result": "ok"}.
    Response to a successful webhook: {"result": "ok"}.
    """

    # Literal["ok"] — поле может содержать только строку "ok".
    # Literal["ok"] means the field can only hold the string "ok".
    result: Literal["ok"]