"""
Tests for business rules: functions are called directly, no server or database.
"""

import pytest

from app.domain import (
    INSTALLMENT_MONTHS,
    UnknownPromoCodeError,
    build_schedule,
    calculate_discount,
    normalize_promo_code,
)

# Tariff prices from the task, in kopecks.
TARIFF_PRICES = [990000, 1990000, 2990000]


# parametrize runs the same test several times with different data.
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KVITTO10", "KVITTO10"),
        ("kvitto10", "KVITTO10"),
        ("  KvItTo10  ", "KVITTO10"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_promo_code(raw: str | None, expected: str | None) -> None:
    assert normalize_promo_code(raw) == expected


def test_no_promo_code_gives_zero_discount() -> None:
    assert calculate_discount(1990000, None) == 0


@pytest.mark.parametrize("code", ["KVITTO10", "kvitto10", "Kvitto10"])
def test_promo_code_is_case_insensitive(code: str) -> None:
    # 10% от 1990000 = 199000
    # 10% of 1990000 = 199000
    assert calculate_discount(1990000, code) == 199000


@pytest.mark.parametrize(
    ("price", "discount", "amount"),
    [
        (990000, 99000, 891000),
        (1990000, 199000, 1791000),
        (2990000, 299000, 2691000),
    ],
)
def test_promo_amounts_for_all_tariffs(price: int, discount: int, amount: int) -> None:
    # We check exact numbers, not just "something was calculated".
    assert calculate_discount(price, "KVITTO10") == discount
    assert price - discount == amount


@pytest.mark.parametrize("code", ["KVITTO20", "SALE", "kvitto 10"])
def test_unknown_promo_code_raises(code: str) -> None:
    # pytest.raises checks that the expected error is raised inside the block.
    with pytest.raises(UnknownPromoCodeError):
        calculate_discount(1990000, code)


def test_discount_rounds_down_to_whole_kopecks() -> None:
    # 10% of 1999 kopecks = 199.9 -> discount is 199, the fraction is dropped.
    assert calculate_discount(1999, "KVITTO10") == 199


def test_schedule_example_from_task() -> None:
    assert build_schedule(1990000, 3) == [663334, 663333, 663333]


@pytest.mark.parametrize("months", INSTALLMENT_MONTHS)
@pytest.mark.parametrize("price", TARIFF_PRICES)
@pytest.mark.parametrize("promo", [None, "KVITTO10"])
def test_schedule_sum_equals_amount(months: int, price: int, promo: str | None) -> None:
    # All tariffs x all terms x with and without promo = 18 checks.
    amount = price - calculate_discount(price, promo)
    schedule = build_schedule(amount, months)

    # The schedule sums up exactly to the amount — the key requirement.
    assert sum(schedule) == amount
    assert len(schedule) == months
    assert max(schedule) - min(schedule) <= 1
    assert schedule == sorted(schedule, reverse=True)


def test_schedule_with_remainder_puts_extra_kopecks_first() -> None:
    # 1000 / 6 = 166 remainder 4 -> the first 4 payments are 167.
    assert build_schedule(1000, 6) == [167, 167, 167, 167, 166, 166]


def test_schedule_rejects_zero_months() -> None:
    with pytest.raises(ValueError):
        build_schedule(1000, 0)
