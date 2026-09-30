"""Расчёт цен для клиента.

См. ARCHITECTURE_PLAN.md §8 (приоритет цены), §16 п.41 (скидки за объём),
§17 (валюты/фиксация).

Приоритет цены (§8):
  1. override_price (жёсткая из CSV) — если задано, используется ВСЕГДА
  2. base_price * (1 - discount_percent/100) — если у клиента есть скидка по бренду
  3. base_price — иначе (розница)

Скидка за объём (§16 п.41) — третий источник, применяется как **максимум** из двух
процентов (бренд-скидка, ступень за объём), ступени не суммируются, а
``override_price`` не подвержен ни одной из них. В каталоге количество неизвестно,
поэтому объёмная скидка там не применяется (лестница публикуется, §8) — она
считается только там, где ``quantity`` известно: корзина и оформление заявки.

Конвертация валюты (§17):
  rate — за `scale` единиц валюты к BYN (НБ РБ: для RUB scale=100).
  amount_currency = amount_byn * scale / rate
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catalog import BrandVolumeTier, Product
from app.models.organization import (
    OrganizationBrandTerm,
    OrganizationPricingAgreement,
)
from app.models.pricing import ExchangeRate, UserBrand
from app.repositories import volume_tiers as tiers_repo
from app.services.cache import VOLUME_TIERS_TAG, cache

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


def volume_tier_ladder(
    tiers: Sequence[BrandVolumeTier],
) -> list[dict]:
    """Лестница бренда для публикации в v2-проекциях (``volumeTiers[]``).

    В каталоге количество неизвестно, поэтому наружу уходит именно лестница —
    по ней UI рисует «от 10 шт −2%», а объёмная цена считается позже, в корзине.
    """
    return [
        {
            "min_qty": tier.min_qty,
            "discount_percent": float(_to_decimal(tier.discount_percent)),
        }
        for tier in tiers
    ]


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


def _tiers_cache_key(brand_id) -> str:
    return f"volume-tiers:{brand_id}"


class PricingService:
    """Сервис, использующий БД для разрешения скидок и курсов."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------- Скидки за объём (§16 п.41) ----------

    async def get_volume_tiers_for_brands(
        self, brand_ids
    ) -> dict:
        """Лестницы брендов: кэш → БД → кэш (fail-open, тег ``volume-tiers``).

        Кэшируются сами лестницы, а не ответы v2-каталога: в ``/api/v2`` кэша
        ответов нет вообще, а лестницы — данные маленькие, меняются редко и
        читаются на каждой строке корзины (§16 п.41 п.9).
        """
        ids = {b for b in brand_ids if b is not None}
        if not ids:
            return {}
        result: dict = {}
        misses = []
        for brand_id in ids:
            cached = await cache.safe_get(_tiers_cache_key(brand_id))
            if cached is None:
                misses.append(brand_id)
            else:
                result[brand_id] = cached
        if misses:
            rows = await tiers_repo.fetch_tiers_for_brands(self.db, set(misses))
            for brand_id in misses:
                ladder = volume_tier_ladder(rows.get(brand_id, []))
                result[brand_id] = ladder
                await cache.safe_set(
                    _tiers_cache_key(brand_id),
                    ladder,
                    ttl=settings.cache_ttl_seconds,
                    tags=[VOLUME_TIERS_TAG, f"brand:{brand_id}"],
                )
        return result

    async def get_volume_tier(self, brand_id, quantity: int) -> dict | None:
        """Лучшая подходящая ступень бренда для количества **строки**."""
        if brand_id is None or not quantity or quantity < 1:
            return None
        ladder = (await self.get_volume_tiers_for_brands({brand_id})).get(brand_id, [])
        return tiers_repo.pick_tier(ladder, quantity)

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
        self,
        product: Product,
        resolved: ResolvedRate,
        discount: Decimal | None,
        *,
        tier: dict | None = None,
    ) -> dict:
        """Цены одного товара при уже разрешённых курсе и скидке (общая часть
        ``price_product`` / ``price_products``).

        ``tier`` — уже выбранная ступень за объём для **этой строки** (§16 п.41).
        Без ``tier`` объёмная скидка не применяется — так считается каталог, где
        количество неизвестно. ``override_price`` перекрывает обе скидки (§8 п.1),
        но сама ступень в ответе остаётся: по ней видно, что за объём был бы скид,
        будь цена не жёсткой из CSV.
        """
        base_byn = _to_decimal(product.base_price)
        tier_percent = _to_decimal(tier["discount_percent"]) if tier else None
        effective = tiers_repo.effective_discount_percent(discount, tier_percent)
        client_byn = client_price_byn(
            product.base_price, product.override_price, effective
        )

        return {
            "base_price_byn": float(_q(base_byn)),
            "retail_price": float(convert_to_currency(base_byn, resolved.rate, resolved.scale)),
            "client_price": float(convert_to_currency(client_byn, resolved.rate, resolved.scale)),
            "currency": resolved.currency,
            "rate_source": resolved.source,
            "has_discount": has_discount(base_byn, client_byn),
            # Ступень, дающая скидку именно этому количеству строки (None — если
            # количество ниже первого порога или лестницы нет). Для DTO каталога
            # это поле не публикуется: там количество ещё не выбрано.
            "volume_tier": tier,
            "discount_percent": (
                float(effective) if effective is not None else None
            ),
        }

    async def price_product(
        self,
        product: Product,
        user,
        calc_mode: str,
        *,
        organization_id=None,
        quantity: int | None = None,
    ) -> dict:
        """Считает цены для одного товара под клиента. Возвращает dict для DTO.

        ``quantity`` передаётся только там, где количество известно (корзина,
        оформление заявки); в каталоге остаётся ``None`` (§8).
        """
        resolved = await self.resolve_rate(
            user, calc_mode, organization_id=organization_id
        )
        selected_organization_id = organization_id
        discount = await self.get_discount_for_brand(
            user.id, product.brand_id, organization_id=selected_organization_id
        )
        tier = (
            await self.get_volume_tier(product.brand_id, quantity)
            if quantity
            else None
        )
        return self._price_one(product, resolved, discount, tier=tier)

    async def price_products(
        self,
        products: Sequence[Product],
        user,
        calc_mode: str,
        *,
        resolved: ResolvedRate | None = None,
        organization_id=None,
        quantities: Mapping | None = None,
    ) -> dict:
        """Батч-расчёт цен: ``{product_id: dict}`` той же структуры, что
        ``price_product``.

        N+1 (аудит 2026-09-06): курс разрешается один раз на батч
        (``resolved`` можно передать уже посчитанный), скидки по всем брендам
        — одним IN-запросом. Формулы/округление — те же чистые функции §8/§17.

        ``quantities`` — ``{product_id: qty}`` для позиций, где количество
        известно (корзина, оформление). Лестницы подгружаются одним батчем и
        кэшируются по тегу ``volume-tiers`` (§16 п.41 п.9). Без ``quantities``
        объёмные скидки не применяются — это путь каталога.
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
        # Лестницы нужны обоим путям: каталог публикует их целиком (количество
        # там неизвестно, §8), корзина/заказ — выбирает из них ступень по своему
        # quantity. Батч + кэш по тегу volume-tiers, N+1 не возникает.
        ladders = await self.get_volume_tiers_for_brands(
            {p.brand_id for p in products}
        )
        result: dict = {}
        for p in products:
            ladder = ladders.get(p.brand_id, [])
            tier = (
                tiers_repo.pick_tier(ladder, quantities.get(p.id))
                if quantities
                else None
            )
            prices = self._price_one(
                p, resolved, discounts.get(p.brand_id), tier=tier
            )
            prices["volume_tiers"] = ladder
            result[p.id] = prices
        return result
