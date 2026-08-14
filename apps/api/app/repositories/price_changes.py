"""Расчёт изменений цен между версиями прайс-листа + поиск получателей дайджеста.

См. ARCHITECTURE_PLAN.md §20.4 (PRICE_CHANGED / PRICE_CHANGED_DIGEST):
  1. сравнение новых base_price/override_price с предыдущей версией;
  2. классификация: up / down / new / override_reset / unchanged;
  3. менеджеру — сводка; клиентам opt-in — дайджест по корзине/избранному/заказам.

Основа diff — ``price_history``: пишется при каждом upsert товара в импорте,
поэтому для каждой версии есть полный снимок цен всех товаров прайса.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import PriceHistory, PriceListVersion, Product
from app.models.enums import PriceListVersionStatus, UserRole
from app.models.order import Cart, CartItem, Order, OrderItem
from app.models.user import Favorite, User


# ----------------------------- DTO -----------------------------

@dataclass(frozen=True)
class ProductPriceChange:
    """Изменение цены одного товара между версиями."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str            # 'up' | 'down' | 'new' | 'override_reset'
    old_base: Decimal | None
    new_base: Decimal
    delta_percent: float | None   # (new-old)/old*100, None если old None/0


@dataclass(frozen=True)
class VersionDiff:
    """Сводка изменений версии относительно предыдущей."""

    version_id: uuid.UUID
    previous_version_id: uuid.UUID | None
    count_up: int
    count_down: int
    count_new: int
    count_override_reset: int
    count_unchanged: int
    changed: list[ProductPriceChange]   # всё кроме unchanged


@dataclass(frozen=True)
class AffectedProduct:
    """Товар из отслеживаемых клиентом позиций, цена которого изменилась."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str
    delta_percent: float | None
    sources: tuple[str, ...]            # ('cart','favorite','orders') — что сработало


@dataclass(frozen=True)
class DigestRecipient:
    """Клиент opt-in + список затронутых позиций для дайджеста."""

    user_id: uuid.UUID
    affected: list[AffectedProduct]


# ----------------------------- queries -----------------------------

async def get_previous_version(
    db: AsyncSession, version_id: uuid.UUID
) -> PriceListVersion | None:
    """Последняя завершённая (DONE) версия перед текущей (§20.4)."""
    return await db.scalar(
        select(PriceListVersion)
        .where(
            PriceListVersion.status == PriceListVersionStatus.DONE,
            PriceListVersion.id != version_id,
        )
        .order_by(PriceListVersion.created_at.desc())
        .limit(1)
    )


def _delta_percent(old_base: Decimal | None, new_base: Decimal) -> float | None:
    """(new-old)/old*100 с округлением до 1 знака. None если old None/0."""
    if old_base is None or old_base == 0:
        return None
    return round(float((new_base - old_base) / old_base * 100), 1)


async def compute_version_diff(
    db: AsyncSession, version_id: uuid.UUID
) -> VersionDiff:
    """Посчитать diff версии относительно предыдущей DONE-версии (§20.4).

    Шаги:
      * снимок цен текущей версии (price_history JOIN products);
      * если предыдущей версии нет — все товары «new»;
      * иначе снимок предыдущей → классификация по категориям.
    """
    prev = await get_previous_version(db, version_id)

    # Снимок новых цен + метаданные товара (sku, name).
    new_rows = (
        await db.execute(
            select(
                PriceHistory.product_id,
                PriceHistory.base_price,
                PriceHistory.override_price,
                Product.sku,
                Product.name,
            )
            .select_from(PriceHistory)
            .join(Product, Product.id == PriceHistory.product_id)
            .where(PriceHistory.price_list_version_id == version_id)
        )
    ).all()

    new_map: dict[uuid.UUID, tuple[Decimal, Decimal | None]] = {}
    meta: dict[uuid.UUID, tuple[str, str]] = {}
    for row in new_rows:
        new_map[row.product_id] = (row.base_price, row.override_price)
        meta[row.product_id] = (row.sku, row.name)

    # Нет предыдущей версии → все товары «новые».
    if prev is None:
        changed = [
            ProductPriceChange(
                product_id=pid,
                sku=meta[pid][0],
                name=meta[pid][1],
                category="new",
                old_base=None,
                new_base=new_base,
                delta_percent=None,
            )
            for pid, (new_base, _override) in new_map.items()
        ]
        return VersionDiff(
            version_id=version_id,
            previous_version_id=None,
            count_up=0,
            count_down=0,
            count_new=len(changed),
            count_override_reset=0,
            count_unchanged=0,
            changed=changed,
        )

    # Снимок цен предыдущей версии.
    prev_rows = (
        await db.execute(
            select(
                PriceHistory.product_id,
                PriceHistory.base_price,
                PriceHistory.override_price,
            ).where(PriceHistory.price_list_version_id == prev.id)
        )
    ).all()
    prev_map: dict[uuid.UUID, tuple[Decimal, Decimal | None]] = {}
    for row in prev_rows:
        prev_map[row.product_id] = (row.base_price, row.override_price)

    count_up = count_down = count_new = count_override_reset = 0
    changed: list[ProductPriceChange] = []
    for pid, (new_base, new_override) in new_map.items():
        prev_base, prev_override = prev_map.get(pid, (None, None))
        sku, name = meta[pid]

        if prev_base is None:
            category = "new"
            old_base: Decimal | None = None
            delta: float | None = None
            count_new += 1
        elif prev_override is not None and new_override is None:
            category = "override_reset"
            old_base = prev_base
            delta = _delta_percent(prev_base, new_base)
            count_override_reset += 1
        elif new_base > prev_base:
            category = "up"
            old_base = prev_base
            delta = _delta_percent(prev_base, new_base)
            count_up += 1
        elif new_base < prev_base:
            category = "down"
            old_base = prev_base
            delta = _delta_percent(prev_base, new_base)
            count_down += 1
        else:
            # Цена не изменилась → в changed не попадает.
            continue

        changed.append(
            ProductPriceChange(
                product_id=pid,
                sku=sku,
                name=name,
                category=category,
                old_base=old_base,
                new_base=new_base,
                delta_percent=delta,
            )
        )

    count_unchanged = len(new_map) - (
        count_up + count_down + count_new + count_override_reset
    )

    return VersionDiff(
        version_id=version_id,
        previous_version_id=prev.id,
        count_up=count_up,
        count_down=count_down,
        count_new=count_new,
        count_override_reset=count_override_reset,
        count_unchanged=count_unchanged,
        changed=changed,
    )


async def find_digest_recipients(
    db: AsyncSession, changed: list[ProductPriceChange]
) -> list[DigestRecipient]:
    """Найти клиентов opt-in, у кого изменились отслеживаемые позиции (§20.4).

    Источники совпадения (по ``price_digest_sources``):
      * 'cart'     — cart_items пользователя;
      * 'favorite' — избранное пользователя;
      * 'orders'   — order_items последних заказов (только product_id, не NULL).

    Сложность O(subscribers × sources) — подписчиков мало, для MVP приемлемо.
    product_snapshot->>'sku' fallback для order_items с NULL product_id не покрыт
    (SET NULL при удалении товара) — дайджест по таким позициям не формируется.
    """
    if not changed:
        return []

    changed_by_id = {c.product_id: c for c in changed}

    # Подписчики: opt-in активные клиенты.
    subs = (
        await db.execute(
            select(User.id, User.price_digest_sources).where(
                User.price_digest_enabled.is_(True),
                User.role == UserRole.CLIENT,
                User.is_active.is_(True),
            )
        )
    ).all()

    recipients: list[DigestRecipient] = []
    for uid, sources in subs:
        sources = sources or []
        sources_hit: dict[uuid.UUID, set[str]] = {}

        if "cart" in sources:
            res = (
                await db.execute(
                    select(CartItem.product_id)
                    .join(Cart, Cart.id == CartItem.cart_id)
                    .where(Cart.user_id == uid)
                    .distinct()
                )
            ).all()
            for (pid,) in res:
                if pid in changed_by_id:
                    sources_hit.setdefault(pid, set()).add("cart")

        if "favorite" in sources:
            res = (
                await db.execute(
                    select(Favorite.product_id).where(Favorite.user_id == uid)
                )
            ).all()
            for (pid,) in res:
                if pid in changed_by_id:
                    sources_hit.setdefault(pid, set()).add("favorite")

        if "orders" in sources:
            res = (
                await db.execute(
                    select(OrderItem.product_id)
                    .join(Order, Order.id == OrderItem.order_id)
                    .where(
                        Order.client_id == uid,
                        OrderItem.product_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            for (pid,) in res:
                if pid in changed_by_id:
                    sources_hit.setdefault(pid, set()).add("orders")

        if not sources_hit:
            continue

        affected = [
            AffectedProduct(
                product_id=pid,
                sku=changed_by_id[pid].sku,
                name=changed_by_id[pid].name,
                category=changed_by_id[pid].category,
                delta_percent=changed_by_id[pid].delta_percent,
                sources=tuple(sorted(sources_hit[pid])),
            )
            for pid in sources_hit
        ]
        recipients.append(DigestRecipient(user_id=uid, affected=affected))

    return recipients
