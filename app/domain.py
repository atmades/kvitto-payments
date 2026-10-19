"""
Business rules for money: promo code, discount, installment schedule.
"""

from enum import StrEnum

PROMO_CODES: dict[str, int] = {"KVITTO10": 10}

INSTALLMENT_MONTHS: tuple[int, ...] = (3, 6, 12)


class UnknownPromoCodeError(ValueError):
    """
    The promo code is not in PROMO_CODES.
    """


def normalize_promo_code(code: str | None) -> str | None:
    """
    Normalizes a promo code: strips surrounding spaces, converts to upper case.
    " kvitto10 " -> "KVITTO10"; None and "" -> None (no promo code given).
    """
    if code is None:
        return None
    # strip() removes surrounding spaces, upper() makes letters upper case.
    normalized = code.strip().upper()
    # An empty string is falsy, so "" turns into None.
    return normalized or None


def calculate_discount(price: int, promo_code: str | None) -> int:
    """
    Discount in kopecks for a tariff price and a promo code.
    No promo code means a zero discount. An unknown code raises UnknownPromoCodeError.
    """
    code = normalize_promo_code(promo_code)
    if code is None:
        return 0
    if code not in PROMO_CODES:
        raise UnknownPromoCodeError(f"Unknown promo code: {promo_code}")
    percent = PROMO_CODES[code]
    # Multiply first, then use integer division (//): no float, no precision loss.
    # If the division were uneven, the fractional kopeck would be dropped.
    return price * percent // 100


def build_schedule(amount: int, months: int) -> list[int]:
    """
    Splits an amount into equal payments; extra kopecks go to the first payments.
    Example: 1990000 over 3 months -> [663334, 663333, 663333].
    """
    if months <= 0:
        raise ValueError("months must be positive")
    # divmod(a, b) returns two numbers at once: the quotient and the remainder.
    # 1990000 / 3 = 663333 with a remainder of 1.
    base, remainder = divmod(amount, months)
    # The first `remainder` payments get +1 kopeck, the rest get `base`.
    # The remainder is always less than months, so there is room for it.
    return [base + 1] * remainder + [base] * (months - remainder)


class PaymentMethod(StrEnum):
    """
    Payment methods from the task.

    StrEnum is an enum whose members are also plain strings:
    PaymentMethod.CARD == "card". Pydantic rejects a typo like "crad" with 422.
    """

    CARD = "card"
    SBP = "sbp"
    INSTALLMENT = "installment"


class PaymentStatus(StrEnum):
    """
    Payment statuses. A new payment always starts as pending.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


# Разрешённые переходы статусов: из какого статуса -> в какие можно перейти.
# Всё, чего нет в таблице, запрещено, в том числе «переход» в тот же статус.
# Allowed status transitions: from a status -> the statuses it may move to.
# Anything missing from the table is forbidden, including "moving" to the same status.
ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset({PaymentStatus.SUCCEEDED, PaymentStatus.FAILED}),
    PaymentStatus.SUCCEEDED: frozenset({PaymentStatus.REFUNDED}),
    PaymentStatus.FAILED: frozenset(),
    PaymentStatus.REFUNDED: frozenset(),
}


def can_transition(current: PaymentStatus, new: PaymentStatus) -> bool:
    """
    Можно ли перевести платёж из статуса current в статус new.
    Whether a payment may move from the current status to the new one.
    """
    return new in ALLOWED_TRANSITIONS[current]
