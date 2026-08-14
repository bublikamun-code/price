"""Расчёт цен для клиента.

См. ARCHITECTURE_PLAN.md §8 (приоритет цены), §17 (валюты/фиксация).

Приоритет цены (§8):
  1. override_price (жёсткая из CSV) — если задано, используется ВСЕГДА
  2. base_price * (1 - discount_percent/100) — если у клиента есть скидка по бренду
  3. base_price — иначе (розница)

Конвертация валюты (§17):
  rate — за `scale` единиц валюты к BYN (НБ РБ: для RUB scale=100).
  amount_currency = amount_byn * scale / rate
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.pricing import ExchangeRate, UserBrand

TWO_PLACES = Decimal("0.01")


def _to_decimal(v) -> Decimal:
    if v is None:
        return None  # type: ignore[return-value]
    return Decimal(str(v))


def _q(value: Decimal) -> Decimal:
    """Округление до копеек (banker's → HALF_UP)."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------- Чистые функции (unit-тестируемые) ----------------
def client_price_byn(
    base_price, override_price, discount_percent
) -> Decimal:
    """Цена со скидкой в BYN по приоритету §8."""
    base = _to_decimal(base_price)
    override = _to_decimal(override_price)

    if override is not None:
        return _q(override)

    if discount_percent is not None and Decimal(str(discount_percent)) > 0:
        d = Decimal(str(discount_percent))
        return _q(base * (Decimal(1) - d / Decimal(100)))
    return _q(base)


def has_discount(base_price, client_price_byn_value) -> bool:
    """Есть ли скидка: клиентская цена строго меньше базовой."""
    return _to_decimal(client_price_byn_value) < _to_decimal(base_price)


def convert_to_currency(amount_byn, rate, scale) -> Decimal:
    """Перевод из BYN в display-валюту.

    rate — BYN за `scale` единиц валюты.
    amount_currency = amount_byn * scale / rate
    Возвращает исходное значение, если rate=None (уже в BYN).
    """
    amount = _to_decimal(amount_byn)
    if rate is None:
        return _q(amount)
    r = Decimal(str(rate))
    s = Decimal(str(scale or 1))
    if r == 0:
        return _q(amount)
    return _q(amount * s / r)


@dataclass(frozen=True)
class ResolvedRate:
    """Результат разрешения курса для клиента."""
    currency: str            # фактическая display-валюта (может упасть до BYN)
    rate: Decimal | None     # None, если BYN
    scale: int
    source: str              # 'BYN' | 'FIXED' | 'NBRB'


class PricingService:
    """Сервис, использующий БД для разрешения скидок и курсов."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_discount_for_brand(
        self, user_id, brand_id
    ) -> Decimal | None:
        if brand_id is None:
            return None
        row = await self.db.scalar(
            select(UserBrand.discount_percent).where(
                UserBrand.user_id == user_id, UserBrand.brand_id == brand_id
            )
        )
        return _to_decimal(row) if row is not None else None

    async def get_latest_rate(self, currency: str) -> ExchangeRate | None:
        """Последний курс для валюты (по fetched_at)."""
        if currency.upper() == "BYN":
            return None
        stmt = (
            select(ExchangeRate)
            .where(ExchangeRate.currency_code == currency.upper())
            .order_by(ExchangeRate.fetched_at.desc())
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def resolve_rate(self, user, calc_mode: str) -> ResolvedRate:
        """Разрешает display-курс: fixed (по договору) | nbrb_current (§17.2/17.3)."""
        currency = (user.display_currency or "BYN").upper()
        if currency == "BYN":
            return ResolvedRate("BYN", None, 1, "BYN")

        # Фиксация по договору
        if calc_mode == "fixed" and user.fixed_rate_id is not None:
            fixed = await self.db.get(ExchangeRate, user.fixed_rate_id)
            if fixed is not None:
                return ResolvedRate(currency, _to_decimal(fixed.rate), fixed.scale or 1, "FIXED")

        # Текущий курс НБ РБ
        rate = await self.get_latest_rate(currency)
        if rate is not None:
            return ResolvedRate(currency, _to_decimal(rate.rate), rate.scale or 1, "NBRB")

        # Курса нет → показываем в BYN (degrade gracefully)
        return ResolvedRate("BYN", None, 1, "BYN")

    async def price_product(self, product: Product, user, calc_mode: str) -> dict:
        """Считает цены для одного товара под клиента. Возвращает dict для DTO."""
        resolved = await self.resolve_rate(user, calc_mode)
        discount = await self.get_discount_for_brand(user.id, product.brand_id)

        base_byn = _to_decimal(product.base_price)
        client_byn = client_price_byn(product.base_price, product.override_price, discount)

        return {
            "base_price_byn": float(_q(base_byn)),
            "retail_price": float(convert_to_currency(base_byn, resolved.rate, resolved.scale)),
            "client_price": float(convert_to_currency(client_byn, resolved.rate, resolved.scale)),
            "currency": resolved.currency,
            "rate_source": resolved.source,
            "has_discount": has_discount(base_byn, client_byn),
        }
