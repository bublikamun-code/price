"""Репозиторий клиентов для менеджер-панели. См. §6, §16 п.19."""
import uuid

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand
from app.models.enums import UserRole
from app.models.order import Order
from app.models.pricing import ExchangeRate, UserBrand
from app.models.user import Session as SessionModel
from app.models.user import User


def _like_escape(s: str) -> str:
    """Экранирует спецсимволы LIKE (\\, %, _), чтобы ввод искался буквально (M7)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def fetch_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Список клиентов с агрегатами: orders_count, avg_discount_percent,
    fixed_rate_currency. Возвращает list[Row] + total."""
    orders_count_sq = (
        select(func.count(Order.id))
        .where(Order.client_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    avg_discount_sq = (
        select(func.avg(UserBrand.discount_percent))
        .where(UserBrand.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    stmt = (
        select(
            User,
            ExchangeRate.currency_code.label("fixed_rate_currency"),
            orders_count_sq.label("orders_count"),
            avg_discount_sq.label("avg_discount_percent"),
        )
        .outerjoin(ExchangeRate, ExchangeRate.id == User.fixed_rate_id)
        .where(User.role == UserRole.CLIENT)
    )
    if q:
        pat = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            or_(User.email.ilike(pat), User.full_name.ilike(pat), User.company.ilike(pat))
        )
    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)

    total_stmt = select(func.count(User.id)).where(User.role == UserRole.CLIENT)
    if q:
        pat = f"%{_like_escape(q)}%"
        total_stmt = total_stmt.where(
            or_(User.email.ilike(pat), User.full_name.ilike(pat), User.company.ilike(pat))
        )
    total = int(await db.scalar(total_stmt) or 0)
    return list(res.all()), total


async def get_client(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.scalar(
        select(User).where(User.id == user_id, User.role == UserRole.CLIENT)
    )


async def get_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    """Пользователь по привязанному Telegram ID (Mini App auth). См. §16 п.27."""
    return await db.scalar(select(User).where(User.telegram_id == telegram_id))


async def email_exists(db: AsyncSession, email: str) -> bool:
    row = await db.scalar(select(User.id).where(func.lower(User.email) == email.lower()))
    return row is not None


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    full_name: str,
    company: str | None,
    phone: str | None,
) -> User:
    user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        company=company,
        phone=phone,
        role=UserRole.CLIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def all_brand_ids(db: AsyncSession) -> list[uuid.UUID]:
    res = await db.execute(select(Brand.id))
    return list(res.scalars().all())


async def fetch_discount_rows(db: AsyncSession, *, user_id: uuid.UUID):
    """Матрица скидок клиента: ВСЕ бренды, без записи — 0. Порядок по имени бренда."""
    stmt = (
        select(
            Brand.id.label("brand_id"),
            Brand.name.label("brand_name"),
            func.coalesce(UserBrand.discount_percent, 0).label("percent"),
        )
        .outerjoin(
            UserBrand,
            (UserBrand.brand_id == Brand.id) & (UserBrand.user_id == user_id),
        )
        .order_by(Brand.name)
    )
    res = await db.execute(stmt)
    return list(res.all())


async def current_discount_map(db: AsyncSession, *, user_id: uuid.UUID) -> dict[str, str]:
    """Текущие строки скидок клиента (для audit before): {brand_id: percent}."""
    res = await db.execute(
        select(UserBrand.brand_id, UserBrand.discount_percent).where(
            UserBrand.user_id == user_id
        )
    )
    return {str(bid): str(percent) for bid, percent in res.all()}


async def replace_discounts(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    items: list[tuple[uuid.UUID, object]],
    manager_id: uuid.UUID,
) -> None:
    """Полная замена матрицы скидок. Коммитит вызывающий."""
    brand_ids = [brand_id for brand_id, _ in items]
    if brand_ids:
        res = await db.execute(select(Brand.id).where(Brand.id.in_(brand_ids)))
        found = set(res.scalars().all())
        missing = [bid for bid in brand_ids if bid not in found]
        if missing:
            raise ValueError(f"Бренд не найден: {missing[0]}")
    await db.execute(delete(UserBrand).where(UserBrand.user_id == user_id))
    for brand_id, percent in items:
        db.add(
            UserBrand(
                user_id=user_id,
                brand_id=brand_id,
                discount_percent=percent,
                updated_by=manager_id,
            )
        )
    await db.flush()


async def revoke_sessions(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    res = await db.execute(
        update(SessionModel)
        .where(SessionModel.user_id == user_id, SessionModel.revoked.is_(False))
        .values(revoked=True)
    )
    return int(res.rowcount or 0)
