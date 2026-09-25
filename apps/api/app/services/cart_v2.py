"""Organization-aware cart use-cases for API v2.

This service owns cart storage semantics. The active organization is resolved by
the router and is never accepted from request input. Prices are recalculated for
the selected commercial scope on every read.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StockStatus
from app.models.order import Cart
from app.repositories import cart as cart_repo
from app.repositories import catalog as catalog_repo
from app.schemas.v2.cart import CartLine, CartSummary, cart_line
from app.schemas.v2.common import (
    MAX_DATABASE_INTEGER,
    Money,
    Rate,
    rate_value,
)
from app.services.pricing import PricingService, ResolvedRate


class CartV2Error(Exception):
    code = "CART_ERROR"
    status_code = 400
    title = "Ошибка корзины"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ProductNotFoundError(CartV2Error):
    code = "PRODUCT_NOT_FOUND"
    status_code = 404
    title = "Товар не найден"


class ProductUnavailableError(CartV2Error):
    code = "PRODUCT_UNAVAILABLE"
    status_code = 400
    title = "Товар недоступен"


class CartItemNotFoundError(CartV2Error):
    code = "CART_ITEM_NOT_FOUND"
    status_code = 404
    title = "Позиция корзины не найдена"


class StaleCartVersionError(CartV2Error):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Корзина уже изменена"


class CartQuantityOverflowError(CartV2Error):
    code = "CART_QUANTITY_OVERFLOW"
    status_code = 422
    title = "Количество превышает допустимое"


class CartV2Service:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingService(db)

    async def _rate(self, user, organization_id: uuid.UUID | None) -> ResolvedRate:
        return await self.pricing.resolve_rate(
            user, "fixed", organization_id=organization_id
        )

    @staticmethod
    def _public_rate(resolved: ResolvedRate) -> Rate:
        return Rate(
            value=rate_value(
                resolved.rate if resolved.rate is not None else Decimal(1)
            ),
            source=resolved.source,
        )

    async def project_locked(
        self,
        user,
        cart: Cart,
        *,
        organization_id: uuid.UUID | None,
        resolved: ResolvedRate,
    ) -> CartSummary:
        rows = await cart_repo.fetch_cart_items_detailed(self.db, cart_id=cart.id)
        products = [row[1] for row in rows if row[1] is not None]
        prices = await self.pricing.price_products(
            products,
            user,
            "fixed",
            resolved=resolved,
            organization_id=organization_id,
        )
        lines: list[CartLine] = []
        total = Decimal(0)
        for row in rows:
            item, product = row[0], row[1]
            if product is None:
                continue
            price = prices[product.id]
            unit_price = Money.from_value(
                price["client_price"], currency=price["currency"]
            )
            line = cart_line(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                brand_name=row.brand_name,
                stock_status=(
                    product.stock_status.value
                    if hasattr(product.stock_status, "value")
                    else str(product.stock_status)
                ),
                quantity=item.quantity,
                note=item.note,
                unit_price=unit_price,
            )
            total += Decimal(line.line_total.amount)
            lines.append(line)
        return CartSummary(
            id=cart.id,
            organization_id=organization_id,
            version=cart.version,
            items=lines,
            total=Money.from_value(total, currency=resolved.currency),
            total_items=len(lines),
            exchange_rate=self._public_rate(resolved),
        )

    async def view(
        self, user, *, organization_id: uuid.UUID | None
    ) -> CartSummary:
        cart = await cart_repo.get_or_create_cart(
            self.db,
            user_id=user.id,
            organization_id=organization_id,
        )
        resolved = await self._rate(user, organization_id)
        return await self.project_locked(
            user, cart, organization_id=organization_id, resolved=resolved
        )

    async def lock_for_mutation(
        self,
        user,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
    ) -> tuple[Cart, ResolvedRate]:
        await cart_repo.get_or_create_cart(
            self.db,
            user_id=user.id,
            organization_id=organization_id,
        )
        cart = await cart_repo.get_cart_for_update(
            self.db,
            user_id=user.id,
            organization_id=organization_id,
        )
        if cart is None:
            raise RuntimeError("scoped cart disappeared while acquiring row lock")
        if cart.version != expected_version:
            raise StaleCartVersionError(
                f"Ожидалась версия {expected_version}, актуальная версия {cart.version}"
            )
        return cart, await self._rate(user, organization_id)

    @staticmethod
    def _ensure_increment_fits(existing_quantity: int, incoming: int) -> None:
        if existing_quantity + incoming > MAX_DATABASE_INTEGER:
            raise CartQuantityOverflowError(
                "Суммарное количество позиции превышает максимум базы данных"
            )

    async def add(
        self,
        user,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
        product_id: uuid.UUID,
        quantity: str,
        note: str | None,
    ) -> CartSummary:
        cart, resolved = await self.lock_for_mutation(
            user,
            organization_id=organization_id,
            expected_version=expected_version,
        )
        products = await catalog_repo.get_by_ids_for_update(self.db, [product_id])
        product = products.get(product_id)
        if product is None:
            raise ProductNotFoundError(f"Товар {product_id} не найден")
        if product.stock_status == StockStatus.ARCHIVED:
            raise ProductUnavailableError(
                f"Товар {product.sku} архивный — недоступен для корзины"
            )
        incoming = int(quantity)
        existing = await cart_repo.get_cart_item(
            self.db, cart_id=cart.id, product_id=product_id
        )
        if existing is not None:
            self._ensure_increment_fits(existing.quantity, incoming)
        await cart_repo.upsert_cart_item(
            self.db,
            cart_id=cart.id,
            product_id=product_id,
            quantity=incoming,
            note=note,
        )
        await cart_repo.bump_cart_version(self.db, cart=cart)
        return await self.project_locked(
            user, cart, organization_id=organization_id, resolved=resolved
        )

    async def replace_item(
        self,
        user,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
        product_id: uuid.UUID,
        quantity: str,
        note: str | None,
    ) -> CartSummary:
        cart, resolved = await self.lock_for_mutation(
            user,
            organization_id=organization_id,
            expected_version=expected_version,
        )
        item = await cart_repo.get_cart_item(
            self.db, cart_id=cart.id, product_id=product_id
        )
        if item is None:
            raise CartItemNotFoundError("Позиции нет в корзине")
        await cart_repo.replace_cart_item(
            self.db, item=item, quantity=int(quantity), note=note
        )
        await cart_repo.bump_cart_version(self.db, cart=cart)
        return await self.project_locked(
            user, cart, organization_id=organization_id, resolved=resolved
        )

    async def delete_item(
        self,
        user,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
        product_id: uuid.UUID,
    ) -> CartSummary:
        cart, resolved = await self.lock_for_mutation(
            user,
            organization_id=organization_id,
            expected_version=expected_version,
        )
        deleted = await cart_repo.delete_cart_item(
            self.db, cart_id=cart.id, product_id=product_id
        )
        if not deleted:
            raise CartItemNotFoundError("Позиции нет в корзине")
        await cart_repo.bump_cart_version(self.db, cart=cart)
        return await self.project_locked(
            user, cart, organization_id=organization_id, resolved=resolved
        )

    async def clear(
        self,
        user,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
    ) -> CartSummary:
        cart, resolved = await self.lock_for_mutation(
            user,
            organization_id=organization_id,
            expected_version=expected_version,
        )
        await cart_repo.clear_cart(self.db, cart_id=cart.id)
        await cart_repo.bump_cart_version(self.db, cart=cart)
        return await self.project_locked(
            user, cart, organization_id=organization_id, resolved=resolved
        )


__all__ = [
    "CartItemNotFoundError",
    "CartQuantityOverflowError",
    "CartV2Error",
    "CartV2Service",
    "ProductNotFoundError",
    "ProductUnavailableError",
    "StaleCartVersionError",
]
