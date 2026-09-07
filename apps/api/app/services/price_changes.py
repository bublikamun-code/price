"""Расчёт изменений цен и подбор получателей дайджеста (§20.4).

Доменные расчёты поверх ``repositories/price_changes`` (§4: сервис не пишет
SQL сам): классификация изменений версий прайса (new/up/down/override_reset/
unchanged) и подбор клиентов opt-in по отслеживаемым позициям
(корзина/избранное/заказы). Создание уведомлений — в
``tasks/notifications.py`` (dispatch_price_changed), тексты — в
``services/notifications.py``.

Модуль восстановлен по контрактам: тесты ``tests/test_price_changes.py``
и вызовы ``tasks/notifications.py`` (оригинал был утерян из
незакоммиченных файлов).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import price_changes as repo


@dataclass
class ProductPriceChange:
    """Изменение цены одного товара между версиями прайса.

    ``sources`` заполняется только для ``affected``-позиций получателя
    дайджеста (через какие источники клиент отслеживает товар).
    """

    product_id: uuid.UUID
    sku: str
    name: str
    category: str  # new | up | down | override_reset | unchanged
    old_base: Decimal | None  # None для category="new"
    new_base: Decimal
    delta_percent: float | None  # None для "new" и "unchanged"
    sources: list[str] = field(default_factory=list)


@dataclass
class VersionDiff:
    """Результат сравнения версии прайса с предыдущей (§20.4)."""

    previous_version_id: uuid.UUID | None
    changed: list[ProductPriceChange] = field(default_factory=list)
    count_new: int = 0
    count_up: int = 0
    count_down: int = 0
    count_override_reset: int = 0
    count_unchanged: int = 0


@dataclass
class DigestRecipient:
    """Получатель PRICE_CHANGED_DIGEST: клиент opt-in и его затронутые позиции."""

    user_id: uuid.UUID
    affected: list[ProductPriceChange] = field(default_factory=list)
    email: str = ""
    telegram_id: int | None = None
    enabled: bool = True


# ----------------------------- helpers -----------------------------

_CATEGORIES = ("new", "up", "down", "override_reset", "unchanged")


def _dec(value: object) -> Decimal:
    """Numeric из БД уже Decimal; приводим на всякий случай без потери точности."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _effective(base: object, override: object | None) -> Decimal:
    """Действующая цена: фикс-цена (override), если задана, иначе базовая."""
    return _dec(override) if override is not None else _dec(base)


def _delta_percent(old: Decimal, new: Decimal) -> float | None:
    """Процент изменения, округлённый до 2 знаков (None при old == 0)."""
    if old == 0:
        return None
    return round(float((new - old) / old * 100), 2)


# ----------------------------- diff версий -----------------------------

async def compute_version_diff(
    db: AsyncSession, version_id: uuid.UUID | str
) -> VersionDiff:
    """Сравнить снимок версии с предыдущей завершённой версией (§20.4).

    Основание — ``price_history``: полный снимок цен каждой версии. Категории
    взаимоисключающие; ``override_reset`` (фикс-цена была и ушла) имеет
    приоритет над up/down. Позиции без изменений в ``changed`` не попадают.
    """
    vid = version_id if isinstance(version_id, uuid.UUID) else uuid.UUID(str(version_id))

    previous = await repo.get_previous_version(db, vid)
    old_prices: dict[uuid.UUID, tuple[object, object | None]] = {}
    if previous is not None:
        for row in await repo.get_version_prices(db, previous.id):
            old_prices[row.product_id] = (row.base_price, row.override_price)

    counts = dict.fromkeys(_CATEGORIES, 0)
    changed: list[ProductPriceChange] = []
    for row in await repo.get_version_prices_with_products(db, vid):
        new_eff = _effective(row.base_price, row.override_price)
        old = old_prices.get(row.product_id)
        if old is None:
            category, old_eff, delta = "new", None, None
        else:
            old_eff = _effective(*old)
            delta = _delta_percent(old_eff, new_eff)
            was_override, now_override = old[1], row.override_price
            if was_override is not None and now_override is None:
                category = "override_reset"
            elif new_eff > old_eff:
                category = "up"
            elif new_eff < old_eff:
                category = "down"
            else:
                category, delta = "unchanged", None
        counts[category] += 1
        if category != "unchanged":
            changed.append(
                ProductPriceChange(
                    product_id=row.product_id,
                    sku=row.sku,
                    name=row.name,
                    category=category,
                    old_base=None if old_eff is None else _dec(old_eff),
                    new_base=new_eff,
                    delta_percent=delta,
                )
            )

    changed.sort(key=lambda c: c.sku)
    return VersionDiff(
        previous_version_id=previous.id if previous is not None else None,
        changed=changed,
        count_new=counts["new"],
        count_up=counts["up"],
        count_down=counts["down"],
        count_override_reset=counts["override_reset"],
        count_unchanged=counts["unchanged"],
    )


# ----------------------------- получатели дайджеста -----------------------------

_SOURCE_FETCHERS = {
    "cart": repo.get_cart_product_ids,
    "favorite": repo.get_favorite_product_ids,
    "orders": repo.get_order_product_ids,
}


async def find_digest_recipients(
    db: AsyncSession, changed: list[ProductPriceChange]
) -> list[DigestRecipient]:
    """Клиенты opt-in, отслеживающие изменившиеся товары (§20.4).

    Пересечение изменившихся позиций с корзиной/избранным/заказами клиента —
    только по источникам из его ``price_digest_sources``. Клиенты без
    затронутых позиций в результат не попадают.
    """
    changed_by_id = {c.product_id: c for c in changed}
    if not changed_by_id:
        return []

    recipients: list[DigestRecipient] = []
    for user_id, telegram_id, digest_sources in await repo.get_digest_subscribers(db):
        tracked: dict[uuid.UUID, set[str]] = {}
        for source in digest_sources or []:
            fetcher = _SOURCE_FETCHERS.get(source)
            if fetcher is None:
                continue
            for row in await fetcher(db, user_id):
                product_id = row[0]
                if product_id in changed_by_id:
                    tracked.setdefault(product_id, set()).add(source)
        if not tracked:
            continue
        affected = [
            replace(c, sources=sorted(tracked[c.product_id]))
            for c in changed
            if c.product_id in tracked
        ]
        recipients.append(
            DigestRecipient(user_id=user_id, affected=affected, telegram_id=telegram_id)
        )

    recipients.sort(key=lambda r: r.user_id)
    return recipients
