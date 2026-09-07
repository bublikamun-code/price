"""Репозиторий администрирования: менеджеры (/api/v1/admin/managers). См. §6, §11."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import Session as SessionModel
from app.models.user import User


async def fetch_managers(db: AsyncSession) -> list[User]:
    """Все менеджеры, свежие сверху (список без пагинации — так ждёт фронт)."""
    res = await db.execute(
        select(User)
        .where(User.role == UserRole.MANAGER)
        .order_by(User.created_at.desc())
    )
    return list(res.scalars().all())


async def get_manager(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Менеджер по id. Пользователи прочих ролей (CLIENT/ADMIN) → None → 404."""
    return await db.scalar(
        select(User).where(User.id == user_id, User.role == UserRole.MANAGER)
    )


async def create_manager(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    full_name: str,
    phone: str | None,
) -> User:
    """Создать менеджера с temp-паролем: обязан сменить его при первом входе."""
    user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        phone=phone,
        role=UserRole.MANAGER,
        is_active=True,
        must_change_password=True,  # §16 п.19: temp-пароль → принудительная смена
    )
    db.add(user)
    await db.flush()
    return user


async def active_session_ids(db: AsyncSession, *, user_id: uuid.UUID) -> list[uuid.UUID]:
    """id активных (не отозванных) сессий — для мгновенной инвалидации кэша."""
    res = await db.execute(
        select(SessionModel.id).where(
            SessionModel.user_id == user_id,
            SessionModel.revoked.is_(False),
        )
    )
    return list(res.scalars().all())
