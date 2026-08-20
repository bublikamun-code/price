"""Сервис аутентификации: login, refresh (rotation), logout.

Модель токенов (см. ARCHITECTURE_PLAN.md §11, §16 фича I):
  - access  — короткий JWT (stateless), содержит sub=user_id, role, sid=session_id
  - refresh — opaque случайная строка; хранится в sessions как SHA-256 хэш.
              Позволяет: ротацию, отзыв, список активных сессий.

Сессии:
  - login  → создаётся новая session, клиенту выдаётся refresh (plain)
  - refresh→ старая session помечается revoked, создаётся новая (rotation)
  - logout → session помечается revoked
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token, verify_password
from app.models.user import ConsentLog, Session as SessionModel, User
from app.schemas.auth import TokenPair, UserUpdate
from app.services.cache import invalidate_tags, user_tag

log = get_logger("app.services.auth")


def _hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _generate_refresh() -> str:
    return secrets.token_urlsafe(48)


class AuthError(Exception):
    """Унифицированная ошибка аутентификации (→ 401 в роутере)."""


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------- login ----------
    async def login(
        self, email: str, password: str, user_agent: str | None, ip: str | None
    ) -> tuple[User, TokenPair]:
        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            # одинаковая ошибка чтобы не светить существование email
            raise AuthError("Неверный email или пароль")
        if not verify_password(password, user.password_hash):
            raise AuthError("Неверный email или пароль")

        token_pair = await self._issue_new_session(user, user_agent, ip)
        log.info("auth.login", user_id=str(user.id), ip=ip)
        return user, token_pair

    # ---------- refresh (rotation) ----------
    async def refresh(
        self, refresh_token_plain: str, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        token_hash = _hash_token(refresh_token_plain)
        session = await self.db.scalar(
            select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        )
        if session is None or session.revoked:
            raise AuthError("Недействительный refresh-токен")
        if session.expires_at <= datetime.now(timezone.utc):
            raise AuthError("Срок действия refresh-токена истёк")

        user = await self.db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise AuthError("Пользователь неактивен")

        # ротация: отзываем старую, создаём новую
        session.revoked = True
        token_pair = await self._issue_new_session(user, user_agent, ip)
        log.info("auth.refresh", user_id=str(user.id), old_sid=str(session.id))
        return token_pair

    # ---------- logout ----------
    async def logout(self, refresh_token_plain: str | None) -> None:
        if not refresh_token_plain:
            return
        token_hash = _hash_token(refresh_token_plain)
        session = await self.db.scalar(
            select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        )
        if session is not None and not session.revoked:
            session.revoked = True
            await self.db.commit()
            log.info("auth.logout", sid=str(session.id))

    # ---------- update profile (PATCH /auth/me, §6 / §20.4 / §16 п.20-6) ----------
    async def update_profile(
        self,
        user: User,
        updates: UserUpdate,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        """Частичное обновление профиля: применяются только явно заданные поля.

        ``null`` в значении трактуется как «поле не задано» (все поля Optional),
        поэтому не затирает прежнее значение в БД.

        Согласие (§16 п.20-6): ``consent_accepted=True`` фиксируется в consent_log
        (ip + user-agent, идемпотентно — повторная отправка не плодит записи);
        ``False`` (отзыв) через API запрещён → 422.
        """
        if updates.consent_accepted is False:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Согласие нельзя отозвать через API",
            )
        # consent_accepted обрабатывается отдельно — на User нет такого поля
        changed = {
            k: v
            for k, v in updates.model_dump(exclude_unset=True).items()
            if v is not None and k != "consent_accepted"
        }
        if updates.consent_accepted is True and user.consent_accepted_at is None:
            accepted_at = datetime.now(timezone.utc)
            user.consent_accepted_at = accepted_at
            self.db.add(
                ConsentLog(
                    user_id=user.id,
                    policy_version="1.0",
                    ip=ip,
                    user_agent=(user_agent or "")[:512] or None,
                    accepted_at=accepted_at,
                )
            )
            log.info("auth.consent_accepted", user_id=str(user.id), ip=ip)
        for field, value in changed.items():
            setattr(user, field, value)
        await self.db.commit()
        if "display_currency" in changed:
            await invalidate_tags(user_tag(user.id))
        logged_fields = list(changed) + (["consent_accepted"] if updates.consent_accepted else [])
        log.info("auth.update_profile", user_id=str(user.id), fields=",".join(logged_fields))
        return user

    # ---------- внутреннее: создание сессии + токенов ----------
    async def _issue_new_session(
        self, user: User, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        refresh_plain = _generate_refresh()
        session = SessionModel(
            user_id=user.id,
            refresh_token_hash=_hash_token(refresh_plain),
            user_agent=(user_agent or "")[:512] or None,
            ip=ip,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_ttl_days),
            revoked=False,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        access = create_access_token(
            subject=str(user.id),
            extra={"role": user.role.value, "sid": str(session.id)},
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh_plain,
            expires_in=settings.access_token_ttl_min * 60,
        )
