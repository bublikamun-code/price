"""FastAPI-зависимости: аутентификация и авторизация (RBAC).

См. ARCHITECTURE_PLAN.md §6, §11.
"""
import secrets
import uuid
from datetime import datetime, timezone
from typing import Sequence

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as m
from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.services.cache import get_session_cached, set_session_cached


def _extract_access_token(request: Request) -> str | None:
    """Достаём access-токен из Authorization: Bearer ... либо из cookie.

    Фронт хранит JWT в cookie `auth_token` (useAuth.persistCookie) — её и
    ждём в первую очередь: без этого <img>/EventSource, которые не могут
    послать заголовок Authorization, получали 401 и фото не отображались.
    `access_token` оставлен как fallback для старых клиентов/мини-приложения.
    """
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get("auth_token") or request.cookies.get("access_token")


def _extract_refresh_token(request: Request) -> str | None:
    body_refresh = getattr(request.state, "refresh_token", None)
    if body_refresh:
        return body_refresh
    return request.cookies.get("refresh_token")


# Логин и второй шаг 2FA-логина освобождены от CSRF: запросы неаутентифицированы,
# креды передаются явно в теле, а не через ambient-куки (ARCHITECTURE_PLAN.md §16 п.21-22).
# Префиксы как в api/v1/router.py + auth.router
_CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/2fa/verify",
    "/api/m/v1/auth/telegram",  # §16 п.27: креды — подписанные initData, не ambient-куки
}


def validate_csrf(request: Request) -> None:
    """Double-submit CSRF для mutating-запросов с cookie-аутентификацией."""
    if request.url.path in _CSRF_EXEMPT_PATHS:
        return
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return
    # Аудит 2026-09-06: фронт аутентифицируется не-httpOnly кукой auth_token
    # (useAuth.persistCookie) — она так же ambient, как httpOnly access_token,
    # поэтому требует того же CSRF-гейта. Имена кук фронта заданы в
    # apps/web/composables/useAuth.ts (persistCookie) и плагине api.ts.
    _AUTH_COOKIES = ("access_token", "refresh_token", "auth_token")
    if not any(request.cookies.get(name) for name in _AUTH_COOKIES):
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(settings.csrf_header_name)
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF-токен отсутствует или неверен")


async def _session_is_active(db: AsyncSession, sid: uuid.UUID) -> bool:
    """Проверяет, что сессия (sid из access-JWT) не отозвана и не истекла.

    Кэш Redis — оптимизация «горячего» пути; отзыв сессии немедленно удаляет
    ключ (invalidate_session), поэтому отзывать токены можно мгновенно (§11).
    Redis down → мимо кэша, читаем БД (fail-open на кэш, не на безопасность).
    """
    cached = await get_session_cached(sid)
    if cached == "1":
        return True
    if cached == "0":
        return False
    session = await db.get(m.Session, sid)
    active = (
        session is not None
        and not session.revoked
        and session.expires_at > datetime.now(timezone.utc)
    )
    await set_session_cached(sid, active)
    return active


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> m.User:
    """Декодирует access-JWT и возвращает активного пользователя.

    Дополнительно проверяет, что сессия (sid) не отозвана: после logout/revoke
    access-токен перестаёт приниматься сразу, а не по истечении TTL (§11).
    """
    token = _extract_access_token(request)
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не авторизован",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise creds_exc
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise creds_exc
    if payload.get("type") != "access":
        raise creds_exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise creds_exc

    sid_raw = payload.get("sid")
    if sid_raw:
        try:
            sid = uuid.UUID(str(sid_raw))
        except (ValueError, TypeError):
            raise creds_exc
        if not await _session_is_active(db, sid):
            raise creds_exc

    user = await db.get(m.User, user_id)
    if user is None or not user.is_active:
        raise creds_exc
    return user


async def get_current_session_id(request: Request) -> uuid.UUID | None:
    """Возвращает sid активной сессии из access-JWT, если он там есть.

    Нужен нативному logout: DELETE /api/v2/auth/sessions/current не несёт refresh
    в теле, а «текущая» сессия однозначно определяется claim'ом, по которому
    сервер и проверяет живость сессии в get_current_user.
    """
    token = _extract_access_token(request)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return None
    raw = payload.get("sid")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def require_role(*roles: UserRole):
    """Зависимость: пускает только пользователей с указанными ролями.

    Использование:
        @router.get("/...", dependencies=[Depends(require_role(UserRole.MANAGER))])
        # или
        async def handler(user=Depends(require_role(UserRole.MANAGER))): ...
    """
    allowed: Sequence[UserRole] = roles

    async def _dependency(user: m.User = Depends(get_current_user)) -> m.User:
        # ADMIN «видит всё»: проходит проверку любой роли.
        if user.role != UserRole.ADMIN and user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _dependency


def require_admin():
    """Зависимость: пускает только пользователей с ролью ADMIN."""

    async def _dependency(user: m.User = Depends(get_current_user)) -> m.User:
        if user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _dependency
