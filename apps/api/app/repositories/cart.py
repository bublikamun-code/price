"""Репозиторий корзины. См. ARCHITECTURE_PLAN.md §19 (persist-корзина в БД)."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, Product, Series
from app.models.order import Cart, CartItem


async def get_or_create_cart(db: AsyncSession, *, user_id: uuid.UUID) -> Cart:
    cart = await db.scalar(select(Cart).where(Cart.user_id == user_id))
    if cart is None:
        cart = Cart(user_id=user_id)
        db.add(cart)
        await db.flush()
    return cart


async def fetch_cart_items(db: AsyncSession, *, cart_id: uuid.UUID) -> list[CartItem]:
    res = await db.execute(
        select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.created_at)
    )
    return list(res.scalars().all())


async def fetch_cart_items_detailed(db: AsyncSession, *, cart_id: uuid.UUID):
    """Позиции корзины с товаром/брендом/серией. Возвращает list[Row]:
    ``row[0]`` — CartItem, ``row[1]`` — Product (или None если удалён),
    ``row.brand_name`` и ``row.photo_key`` — labeled-колонки (могут быть None)."""
    stmt = (
        select(
            CartItem,
            Product,
            Brand.name.label("brand_name"),
            Series.photo_key.label("photo_key"),
        )
        .outerjoin(Product, Product.id == CartItem.product_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .outerjoin(Series, Series.id == Product.series_id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.created_at)
    )
    res = await db.execute(stmt)
    return res.all()


async def get_cart_item(
    db: AsyncSession, *, cart_id: uuid.UUID, product_id: uuid.UUID
) -> CartItem | None:
    return await db.scalar(
        select(CartItem).where(
            CartItem.cart_id == cart_id, CartItem.product_id == product_id
        )
    )


async def upsert_cart_item(
    db: AsyncSession,
    *,
    cart_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: int,
    note: str | None,
) -> CartItem:
    """Добавить (создать) или увеличить quantity если уже есть."""
    existing = await get_cart_item(db, cart_id=cart_id, product_id=product_id)
    if existing is not None:
        existing.quantity += quantity
        if note is not None:
            existing.note = note
        await db.flush()
        return existing
    item = CartItem(cart_id=cart_id, product_id=product_id, quantity=quantity, note=note)
    db.add(item)
    await db.flush()
    return item


async def update_cart_item(
    db: AsyncSession, *, item: CartItem, quantity: int | None, note: str | None
) -> CartItem:
    if quantity is not None:
        item.quantity = quantity
    if note is not None:
        item.note = note
    await db.flush()
    return item


async def delete_cart_item(
    db: AsyncSession, *, cart_id: uuid.UUID, product_id: uuid.UUID
) -> bool:
    res = await db.execute(
        delete(CartItem).where(
            CartItem.cart_id == cart_id, CartItem.product_id == product_id
        )
    )
    return (res.rowcount or 0) > 0


async def clear_cart(db: AsyncSession, *, cart_id: uuid.UUID) -> int:
    res = await db.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
    return res.rowcount or 0
