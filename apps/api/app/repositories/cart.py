"""Scoped cart persistence used by legacy API v1 and organization-aware API v2."""
import uuid

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, Product, Series
from app.models.order import Cart, CartItem


def _scope_filter(*, user_id: uuid.UUID, organization_id: uuid.UUID | None):
    if organization_id is None:
        return and_(Cart.user_id == user_id, Cart.organization_id.is_(None))
    return and_(
        Cart.user_id == user_id,
        Cart.organization_id == organization_id,
    )


async def get_or_create_cart(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> Cart:
    """Return one cart for a user/scope, creating it atomically when absent."""
    where = _scope_filter(user_id=user_id, organization_id=organization_id)
    cart = await db.scalar(select(Cart).where(where))
    if cart is not None:
        return cart

    if organization_id is None:
        conflict_filter = Cart.organization_id.is_(None)
        conflict_columns = [Cart.user_id]
    else:
        conflict_filter = Cart.organization_id.is_not(None)
        conflict_columns = [Cart.user_id, Cart.organization_id]

    stmt = (
        pg_insert(Cart)
        .values(
            user_id=user_id,
            organization_id=organization_id,
            name="Корзина",
            id=uuid.uuid4(),
            version=1,
        )
        .on_conflict_do_nothing(
            index_elements=conflict_columns,
            index_where=conflict_filter,
        )
    )
    await db.execute(stmt)
    cart = await db.scalar(select(Cart).where(where))
    if cart is None:
        raise RuntimeError(
            f"cart for user {user_id}, organization {organization_id} missing after upsert"
        )
    return cart


async def get_cart_for_update(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> Cart | None:
    return await db.scalar(
        select(Cart)
        .where(
            _scope_filter(user_id=user_id, organization_id=organization_id)
        )
        .with_for_update()
    )


async def bump_cart_version(db: AsyncSession, *, cart: Cart) -> int:
    cart.version += 1
    await db.flush()
    return cart.version


async def fetch_cart_items(db: AsyncSession, *, cart_id: uuid.UUID) -> list[CartItem]:
    res = await db.execute(
        select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.created_at)
    )
    return list(res.scalars().all())


async def fetch_cart_items_detailed(db: AsyncSession, *, cart_id: uuid.UUID):
    """Cart lines with safe presentation joins plus the legacy photo key.

    Row shape is ``row[0]=CartItem``, ``row[1]=Product`` and labeled
    ``brand_name``/``photo_key``. API v2 deliberately ignores ``photo_key``.
    """
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
    """Add a line or increment it if the product is already present."""
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
    """Legacy partial update: omitted/null note leaves the existing note."""
    if quantity is not None:
        item.quantity = quantity
    if note is not None:
        item.note = note
    await db.flush()
    return item


async def replace_cart_item(
    db: AsyncSession,
    *,
    item: CartItem,
    quantity: int,
    note: str | None,
) -> CartItem:
    """V2 full replacement; ``note=None`` explicitly clears the note."""
    item.quantity = quantity
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
