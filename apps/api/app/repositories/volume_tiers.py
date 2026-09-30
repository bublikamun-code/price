"""Репозиторий лестниц скидок за объём (``brand_volume_tiers``, §16 п.41).

Порог задаётся на бренд и сравнивается с количеством **одной строки** корзины или
заказа — не суммой по бренду. Действует одна ступень: наибольшая с
``min_qty <= quantity``; ступени не суммируются, а с процентом по бренду берётся
максимум из двух (§8).

Коммитит вызывающий (паттерн §4: сервис — flush, роутер — commit).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import BrandVolumeTier

# Порядок для «лучшей подходящей» ступени: по возрастанию порога, чтобы
# ``pick_tier`` могла смотреть только на строки с ``min_qty <= quantity``.
_ORDER = (BrandVolumeTier.min_qty.asc(),)


async def fetch_tiers_for_brands(
    db: AsyncSession, brand_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[BrandVolumeTier]]:
    """Лестницы нескольких брендов одним запросом (N+1 на список корзины не делаем)."""
    ids = {b for b in brand_ids if b is not None}
    if not ids:
        return {}
    res = await db.execute(
        select(BrandVolumeTier)
        .where(BrandVolumeTier.brand_id.in_(ids))
        .order_by(*_ORDER)
    )
    grouped: dict[uuid.UUID, list[BrandVolumeTier]] = {bid: [] for bid in ids}
    for tier in res.scalars().all():
        grouped[tier.brand_id].append(tier)
    return grouped


async def fetch_tiers(
    db: AsyncSession, brand_id: uuid.UUID
) -> list[BrandVolumeTier]:
    res = await db.execute(
        select(BrandVolumeTier)
        .where(BrandVolumeTier.brand_id == brand_id)
        .order_by(*_ORDER)
    )
    return list(res.scalars().all())


async def get_tier(db: AsyncSession, tier_id: uuid.UUID) -> BrandVolumeTier | None:
    return await db.scalar(select(BrandVolumeTier).where(BrandVolumeTier.id == tier_id))


async def find_tier_by_threshold(
    db: AsyncSession, *, brand_id: uuid.UUID, min_qty: int
) -> BrandVolumeTier | None:
    return await db.scalar(
        select(BrandVolumeTier).where(
            BrandVolumeTier.brand_id == brand_id,
            BrandVolumeTier.min_qty == min_qty,
        )
    )


def pick_tier(ladder: list[dict], quantity: int | None) -> dict | None:
    """Наибольшая ступень с ``min_qty <= quantity``.

    Ступени не суммируются (§8): «от 10 −2%, от 50 −5%» на 50 шт даёт −5%,
    а не −7%. Список обязан быть отсортирован по ``min_qty`` — берём последнюю
    подходящую, а не максимум по проценту: при одинаковых процентах на разных
    порогах «лучшей» считается та, что достижима.
    """
    if not quantity or quantity < 1:
        return None
    chosen: dict | None = None
    for tier in ladder:
        if tier["min_qty"] <= quantity:
            chosen = tier
        else:
            break
    return chosen


def effective_discount_percent(
    brand_percent: Decimal | None, tier_percent: Decimal | None
) -> Decimal | None:
    """Скидка по бренду и скидка за объём — **максимум из двух**, не сумма (§8).

    Суммирование на B2B-прайсе даёт неконтролируемую маржу; «максимум» — правило,
    которое менеджер проверяет глазами по двум числам.
    """
    values = [v for v in (brand_percent, tier_percent) if v is not None and v > 0]
    return max(values) if values else None


__all__ = [
    "effective_discount_percent",
    "fetch_tiers",
    "fetch_tiers_for_brands",
    "find_tier_by_threshold",
    "get_tier",
    "pick_tier",
]
