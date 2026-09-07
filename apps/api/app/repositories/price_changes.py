"""Запросы для расчёта изменений цен и дайджеста (§20.4).

Только доступ к данным (§4): снимки цен версий из ``price_history``,
подписчики opt-in и отслеживаемые позиции клиента. Доменные расчёты
(классификация изменений, подбор получателей) — в ``services/price_changes``.

Основа diff — ``price_history``: пишется при каждом upsert товара в импорте,
поэтому для каждой версии есть полный снимок цен всех товаров прайса.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import PriceHistory, PriceListVersion, Product
from app.models.enums import PriceListVersionStatus, UserRole
from app.models.order import Cart, CartItem, Order, OrderItem
from app.models.user import Favorite, User


# ----------------------------- версии и снимки цен -----------------------------

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


async def get_version_prices_with_products(
    db: AsyncSession, version_id: uuid.UUID
) -> list:
    """Снимок цен версии + метаданные товара (sku, name) через JOIN products."""
    return (
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


async def get_version_prices(db: AsyncSession, version_id: uuid.UUID) -> list:
    """Снимок цен версии: (product_id, base_price, override_price)."""
    return (
        await db.execute(
            select(
                PriceHistory.product_id,
                PriceHistory.base_price,
                PriceHistory.override_price,
            ).where(PriceHistory.price_list_version_id == version_id)
        )
    ).all()


# ----------------------------- подписчики дайджеста -----------------------------

async def get_digest_subscribers(db: AsyncSession) -> list:
    """Подписчики: opt-in активные клиенты (§20.4).

    Возвращает тройки ``(user_id, telegram_id, price_digest_sources)``;
    ``telegram_id`` — chat_id для TG-доставки дайджеста (None если не привязан).
    """
    return (
        await db.execute(
            select(User.id, User.telegram_id, User.price_digest_sources).where(
                User.price_digest_enabled.is_(True),
                User.role == UserRole.CLIENT,
                User.is_active.is_(True),
            )
        )
    ).all()


async def get_cart_product_ids(db: AsyncSession, user_id: uuid.UUID) -> list:
    """Все product_id из корзин пользователя (distinct)."""
    return (
        await db.execute(
            select(CartItem.product_id)
            .join(Cart, Cart.id == CartItem.cart_id)
            .where(Cart.user_id == user_id)
            .distinct()
        )
    ).all()


async def get_favorite_product_ids(db: AsyncSession, user_id: uuid.UUID) -> list:
    """product_id из избранного пользователя."""
    return (
        await db.execute(select(Favorite.product_id).where(Favorite.user_id == user_id))
    ).all()


async def get_order_product_ids(db: AsyncSession, user_id: uuid.UUID) -> list:
    """product_id из заказов клиента (только не NULL; distinct).

    product_snapshot->>'sku' fallback для order_items с NULL product_id не
    покрыт (SET NULL при удалении товара) — см. services/price_changes.
    """
    return (
        await db.execute(
            select(OrderItem.product_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.client_id == user_id,
                OrderItem.product_id.is_not(None),
            )
            .distinct()
        )
    ).all()
