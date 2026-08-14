"""FastAPI-зависимости: аутентификация и авторизация (RBAC).

См. ARCHITECTURE_PLAN.md §6, §11.
"""
import secrets
import uuid
from typing import Sequence

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as m
from app.core.config import settings
from app.core.security import JWTError, decode_token
from app.db.session import get_db
from app.models.enums import UserRole


def _extract_access_token(request: Request) -> str | None:
    """Достаём access-токен из Authorization: Bearer ... либо из cookie."""
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get("access_token")


def _extract_refresh_token(request: Request) -> str | None:
    body_refresh = getattr(request.state, "refresh_token", None)
    if body_refresh:
        return body_refresh
    return request.cookies.get("refresh_token")


def validate_csrf(request: Request) -> None:
    """Double-submit CSRF для mutating-запросов с cookie-аутентификацией."""
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return
    if not (request.cookies.get("access_token") or request.cookies.get("refresh_token")):
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(settings.csrf_header_name)
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF-токен отсутствует или неверен")


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> m.User:
    """Декодирует access-JWT и возвращает активного пользователя."""
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
    except JWTError:
        raise creds_exc
    if payload.get("type") != "access":
        raise creds_exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise creds_exc

    user = await db.get(m.User, user_id)
    if user is None or not user.is_active:
        raise creds_exc
    return user


def require_role(*roles: UserRole):
    """Зависимость: пускает только пользователей с указанными ролями.

    Использование:
        @router.get("/...", dependencies=[Depends(require_role(UserRole.MANAGER))])
        # или
        async def handler(user=Depends(require_role(UserRole.MANAGER))): ...
    """
    allowed: Sequence[UserRole] = roles

    async def _dependency(user: m.User = Depends(get_current_user)) -> m.User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _dependency
