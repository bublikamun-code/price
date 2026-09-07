"""Сервис администрирования: менеджеры (/api/v1/admin/managers). См. §6, §11.

Создание менеджера с temp-паролем (паттерн §16 п.19), блокировка/разблокировка
с немедленным отзывом активных сессий, правка профиля. Коммит выполняет сервис;
мутации пишут audit_log (repositories/audit.py).
Ошибки: NotFoundError → 404, ConflictError → 409, обычный ValueError → 422.
"""
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User
from app.repositories import admin as admin_repo
from app.repositories import audit as audit_repo
from app.repositories import notifications as notif_repo
from app.repositories import users as users_repo
from app.schemas.admin import (
    AdminManagerIn,
    AdminManagerOut,
    AdminManagerPatchIn,
)
from app.services.cache import invalidate_session
from app.services.notification_events import notification_payload, publish_notification


class NotFoundError(ValueError):
    """Менеджер не найден → 404."""


class ConflictError(ValueError):
    """Конфликт состояния (дубликат email) → 409."""


class AdminUsersService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------ helpers
    def to_out(self, user: User) -> AdminManagerOut:
        return AdminManagerOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            is_active=user.is_active,
            created_at=user.created_at,
        )

    # -------------------------------------------------------------- list
    async def list_managers(self) -> list[AdminManagerOut]:
        users = await admin_repo.fetch_managers(self.db)
        return [self.to_out(u) for u in users]

    # ------------------------------------------------------------- create
    async def create_manager(
        self, admin: User, payload: AdminManagerIn
    ) -> tuple[User, str]:
        email = payload.email.lower()
        if await users_repo.email_exists(self.db, email):
            raise ConflictError("Пользователь с таким email уже существует")

        temp_password = secrets.token_urlsafe(12)
        user = await admin_repo.create_manager(
            self.db,
            email=email,
            password_hash=hash_password(temp_password),
            full_name=payload.full_name,
            phone=payload.phone,
        )
        await audit_repo.create_audit(
            self.db,
            actor_id=admin.id,
            action="manager.create",
            target_type="user",
            target_id=user.id,
            after={"email": email, "full_name": payload.full_name, "phone": payload.phone},
        )
        notif = await notif_repo.create_notification(
            self.db,
            type="ACCOUNT_CREATED",
            user_id=user.id,
            channel=["inapp"],
            title="Аккаунт создан",
            body="Доступ к порталу создан. Временный пароль выдал администратор.",
        )
        # SSE-событие (§16 п.26): короткий sync-publish, fail-open.
        publish_notification(notification_payload(notif), user_id=user.id)
        await self.db.commit()
        await self.db.refresh(user)
        return user, temp_password

    # ------------------------------------------------------------ update
    async def update_manager(
        self, admin: User, manager_id: uuid.UUID, payload: AdminManagerPatchIn
    ) -> User:
        user = await admin_repo.get_manager(self.db, manager_id)
        if user is None:
            raise NotFoundError("Менеджер не найден")

        data = payload.model_dump(exclude_unset=True)
        before: dict = {}
        after: dict = {}
        for field in ("full_name", "phone"):
            value = data.get(field)
            if value is None:
                continue
            if getattr(user, field) != value:
                before[field] = getattr(user, field)
                after[field] = value
                setattr(user, field, value)

        if data.get("is_active") is not None and user.is_active != data["is_active"]:
            before["is_active"] = user.is_active
            after["is_active"] = data["is_active"]
            user.is_active = data["is_active"]
            if not data["is_active"]:
                # Блокировка: активные сессии завершаются немедленно — отзыв в БД
                # + инвалидация кэша сессий (§11), иначе «хвост» жил бы до TTL кэша.
                sids = await admin_repo.active_session_ids(self.db, user_id=user.id)
                after["sessions_revoked"] = await users_repo.revoke_sessions(
                    self.db, user_id=user.id
                )
                for sid in sids:
                    await invalidate_session(sid)

        if after:
            await audit_repo.create_audit(
                self.db,
                actor_id=admin.id,
                action="manager.update",
                target_type="user",
                target_id=user.id,
                before=before,
                after=after,
            )
            await self.db.commit()
            await self.db.refresh(user)
        return user
