"""Unit-тесты формулы ценообразования и конвертации валют.

Покрывают бизнес-логику §8 (приоритет цены) и §17 (конвертация).
Без БД — чистые функции.
"""
from decimal import Decimal

from app.services.pricing import (
    client_price_byn,
    convert_to_currency,
    has_discount,
)


# ---------------- client_price_byn: приоритет §8 ----------------
def test_price_override_takes_priority():
    """override_price используется всегда, игнорируя скидку."""
    p = client_price_byn(base_price=100, override_price=80, discount_percent=20)
    assert p == Decimal("80.00")


def test_price_with_discount_percent():
    p = client_price_byn(base_price=100, override_price=None, discount_percent=10)
    assert p == Decimal("90.00")


def test_price_no_discount_returns_base():
    p = client_price_byn(base_price=100, override_price=None, discount_percent=None)
    assert p == Decimal("100.00")


def test_price_discount_zero_returns_base():
    """Скидка 0% = нет скидки."""
    p = client_price_byn(base_price=250, override_price=None, discount_percent=0)
    assert p == Decimal("250.00")


def test_price_discount_rounds_half_up():
    p = client_price_byn(base_price=99.99, override_price=None, discount_percent=15)
    # 99.99 * 0.85 = 84.9915 → 84.99
    assert p == Decimal("84.99")


def test_price_fractional_discount():
    p = client_price_byn(base_price=1000, override_price=None, discount_percent=12.5)
    assert p == Decimal("875.00")


# ---------------- has_discount ----------------
def test_has_discount_true():
    assert has_discount(base_price=100, client_price_byn_value=90) is True


def test_has_discount_false_when_equal():
    assert has_discount(base_price=100, client_price_byn_value=100) is False


def test_has_discount_false_when_override_higher_than_base():
    """override может быть выше базы — тогда скидки нет."""
    assert has_discount(base_price=100, client_price_byn_value=120) is False


# ---------------- convert_to_currency (§17) ----------------
def test_convert_byn_no_rate():
    """rate=None → возвращаем как есть (уже BYN)."""
    assert convert_to_currency(amount_byn=Decimal("100"), rate=None, scale=1) == Decimal("100.00")


def test_convert_usd_scale_1():
    """1 USD = 3.27 BYN → 100 BYN = 30.58 USD."""
    got = convert_to_currency(amount_byn=Decimal("100"), rate=Decimal("3.27"), scale=1)
    assert got == Decimal("30.58")


def test_convert_rub_scale_100():
    """100 RUB = 3.5 BYN (scale=100, rate=3.5) → 100 BYN = 2857.14 RUB."""
    got = convert_to_currency(amount_byn=Decimal("100"), rate=Decimal("3.5"), scale=100)
    assert got == Decimal("2857.14")


def test_convert_eur_rounding():
    got = convert_to_currency(amount_byn=Decimal("10"), rate=Decimal("3.5"), scale=1)
    # 10/3.5 = 2.857.. → 2.86
    assert got == Decimal("2.86")


def test_convert_zero_rate_safe():
    """rate=0 не должен ронять (возвращаем исходное)."""
    got = convert_to_currency(amount_byn=Decimal("100"), rate=Decimal("0"), scale=1)
    assert got == Decimal("100.00")
