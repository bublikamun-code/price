"""Сервис корзины (persist в БД). См. ARCHITECTURE_PLAN.md §19.

Корзина — одна активная на пользователя. Актуальные цены считаются через
``PricingService`` на лету (в корзине цена НЕ замораживается — только в заказе).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StockStatus
from app.repositories import cart as cart_repo, catalog as catalog_repo
from app.schemas.cart import (
    CartBulkAddOut,
    CartBulkAdded,
    CartBulkItemIn,
    CartBulkRejected,
    CartItemRead,
    CartRead,
)
from app.services.pricing import PricingService


class CartService:
    """Операции с корзиной текущего пользователя."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingService(db)

    async def view(self, user) -> CartRead:
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)
        rows = await cart_repo.fetch_cart_items_detailed(self.db, cart_id=cart.id)

        items: list[CartItemRead] = []
        total = 0.0
        for row in rows:
            item, product = row[0], row[1]
            if product is None:
                # Товар удалён (hard-delete через CASCADE невозможен при soft-delete,
                # но защищаемся): позицию пропускаем в выдаче.
                continue
            pr = await self.pricing.price_product(product, user, "fixed")
            unit_price = float(pr["client_price"])
            line_total = round(unit_price * item.quantity, 2)
            total += line_total
            items.append(
                CartItemRead(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    brand_name=row.brand_name,
                    photo_key=row.photo_key,
                    stock_status=product.stock_status.value
                    if hasattr(product.stock_status, "value")
                    else str(product.stock_status),
                    quantity=item.quantity,
                    note=item.note,
                    unit_price=unit_price,
                    currency=pr["currency"],
                    line_total=line_total,
                )
            )
        return CartRead(
            id=cart.id, items=items, total_amount=round(total, 2), total_items=len(items)
        )

    async def add(self, user, sku: str, quantity: int, note: str | None) -> CartRead:
        product = await catalog_repo.get_by_sku(self.db, sku)
        if product is None:
            raise ValueError("Товар не найден")
        if product.stock_status == StockStatus.ARCHIVED:
            raise ValueError("Архивный товар нельзя добавить в корзину")
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)
        await cart_repo.upsert_cart_item(
            self.db, cart_id=cart.id, product_id=product.id, quantity=quantity, note=note
        )
        return await self.view(user)

    async def add_bulk(
        self, user, items: list[CartBulkItemIn]
    ) -> CartBulkAddOut:
        """Массовое добавление позиций (§16 п.20-5) — частичный успех.

        Разрешает все артикулы одним batch-запросом, валидные позиции
        аккумулирует в корзине через ``upsert_cart_item``; невалидные
        (не найден / архив) собирает в ``rejected`` с RU-причиной.
        Не коммитит — транзакцию закрывает роутер.
        """
        products = await catalog_repo.get_by_skus(
            self.db, [item.sku for item in items]
        )
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)

        added: list[CartBulkAdded] = []
        rejected: list[CartBulkRejected] = []
        for item in items:
            product = products.get(item.sku)
            if product is None:
                rejected.append(CartBulkRejected(sku=item.sku, reason="Товар не найден"))
                continue
            if product.stock_status == StockStatus.ARCHIVED:
                rejected.append(CartBulkRejected(sku=item.sku, reason="Товар в архиве"))
                continue
            row = await cart_repo.upsert_cart_item(
                self.db, cart_id=cart.id, product_id=product.id,
                quantity=item.qty, note=None,
            )
            added.append(CartBulkAdded(sku=item.sku, quantity=row.quantity))
        return CartBulkAddOut(added=added, rejected=rejected)

    async def update(
        self, user, sku: str, quantity: int | None, note: str | None
    ) -> CartRead:
        product = await catalog_repo.get_by_sku(self.db, sku)
        if product is None:
            raise ValueError("Товар не найден")
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)
        item = await cart_repo.get_cart_item(
            self.db, cart_id=cart.id, product_id=product.id
        )
        if item is None:
            raise ValueError("Позиции нет в корзине")
        await cart_repo.update_cart_item(self.db, item=item, quantity=quantity, note=note)
        return await self.view(user)

    async def delete_item(self, user, sku: str) -> CartRead:
        product = await catalog_repo.get_by_sku(self.db, sku)
        if product is None:
            raise ValueError("Товар не найден")
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)
        ok = await cart_repo.delete_cart_item(
            self.db, cart_id=cart.id, product_id=product.id
        )
        if not ok:
            raise ValueError("Позиции нет в корзине")
        return await self.view(user)

    async def clear(self, user) -> CartRead:
        cart = await cart_repo.get_or_create_cart(self.db, user_id=user.id)
        await cart_repo.clear_cart(self.db, cart_id=cart.id)
        return await self.view(user)
