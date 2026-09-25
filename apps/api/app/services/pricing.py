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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.organization import (
    OrganizationBrandTerm,
    OrganizationPricingAgreement,
)
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
        self, user_id, brand_id, *, organization_id=None
    ) -> Decimal | None:
        if brand_id is None:
            return None
        if organization_id is not None:
            row = await self.db.scalar(
                select(OrganizationBrandTerm.discount_percent).where(
                    OrganizationBrandTerm.organization_id == organization_id,
                    OrganizationBrandTerm.brand_id == brand_id,
                )
            )
            return _to_decimal(row) if row is not None else None
        row = await self.db.scalar(
            select(UserBrand.discount_percent).where(
                UserBrand.user_id == user_id, UserBrand.brand_id == brand_id
            )
        )
        return _to_decimal(row) if row is not None else None

    async def get_discounts_for_brands(
        self, user_id, brand_ids, *, organization_id=None
    ) -> dict:
        """Return discounts for several brands, preferring organization terms.

        In an organization scope, a missing organization term is intentionally
        not filled from the legacy user term. User terms are used only in the
        legacy USER scope.
        """
        ids = {b for b in brand_ids if b is not None}
        if not ids:
            return {}
        discounts: dict = {}
        if organization_id is not None:
            res = await self.db.execute(
                select(
                    OrganizationBrandTerm.brand_id,
                    OrganizationBrandTerm.discount_percent,
                ).where(
                    OrganizationBrandTerm.organization_id == organization_id,
                    OrganizationBrandTerm.brand_id.in_(ids),
                )
            )
            discounts = {bid: _to_decimal(d) for bid, d in res.all()}
        missing = ids - discounts.keys()
        if missing and organization_id is None:
            res = await self.db.execute(
                select(UserBrand.brand_id, UserBrand.discount_percent).where(
                    UserBrand.user_id == user_id,
                    UserBrand.brand_id.in_(missing),
                )
            )
            discounts.update({bid: _to_decimal(d) for bid, d in res.all()})
        return discounts

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

    async def resolve_rate(
        self, user, calc_mode: str, *, organization_id=None
    ) -> ResolvedRate:
        """Resolve organization terms first, then legacy user terms."""
        selected_organization_id = organization_id
        agreement = None
        if selected_organization_id is not None:
            agreement = await self.db.scalar(
                select(OrganizationPricingAgreement).where(
                    OrganizationPricingAgreement.organization_id
                    == selected_organization_id
                )
            )

        currency = (
            (agreement.display_currency if agreement is not None else user.display_currency)
            or "BYN"
        ).upper()
        if currency == "BYN":
            return ResolvedRate("BYN", None, 1, "BYN")

        fixed_rate_id = (
            agreement.fixed_rate_id
            if agreement is not None
            else user.fixed_rate_id
        )
        if calc_mode == "fixed" and fixed_rate_id is not None:
            fixed = await self.db.get(ExchangeRate, fixed_rate_id)
            if fixed is not None:
                return ResolvedRate(
                    currency,
                    _to_decimal(fixed.rate),
                    fixed.scale or 1,
                    "FIXED",
                )

        # Текущий курс НБ РБ
        rate = await self.get_latest_rate(currency)
        if rate is not None:
            return ResolvedRate(currency, _to_decimal(rate.rate), rate.scale or 1, "NBRB")

        # Курса нет → показываем в BYN (degrade gracefully)
        return ResolvedRate("BYN", None, 1, "BYN")

    def _price_one(
        self, product: Product, resolved: ResolvedRate, discount: Decimal | None
    ) -> dict:
        """Цены одного товара при уже разрешённых курсе и скидке (общая часть
        ``price_product`` / ``price_products``)."""
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

    async def price_product(
        self, product: Product, user, calc_mode: str, *, organization_id=None
    ) -> dict:
        """Считает цены для одного товара под клиента. Возвращает dict для DTO."""
        resolved = await self.resolve_rate(
            user, calc_mode, organization_id=organization_id
        )
        selected_organization_id = organization_id
        discount = await self.get_discount_for_brand(
            user.id, product.brand_id, organization_id=selected_organization_id
        )
        return self._price_one(product, resolved, discount)

    async def price_products(
        self,
        products: Sequence[Product],
        user,
        calc_mode: str,
        *,
        resolved: ResolvedRate | None = None,
        organization_id=None,
    ) -> dict:
        """Батч-расчёт цен: ``{product_id: dict}`` той же структуры, что
        ``price_product``.

        N+1 (аудит 2026-09-06): курс разрешается один раз на батч
        (``resolved`` можно передать уже посчитанный), скидки по всем брендам
        — одним IN-запросом. Формулы/округление — те же чистые функции §8/§17.
        """
        if resolved is None:
            resolved = await self.resolve_rate(
                user, calc_mode, organization_id=organization_id
            )
        selected_organization_id = organization_id
        discounts = await self.get_discounts_for_brands(
            user.id,
            [p.brand_id for p in products],
            organization_id=selected_organization_id,
        )
        return {
            p.id: self._price_one(p, resolved, discounts.get(p.brand_id))
            for p in products
        }
