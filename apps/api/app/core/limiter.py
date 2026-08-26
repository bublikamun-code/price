"""Rate-limiting (slowapi). См. ARCHITECTURE_PLAN.md §11.

Лимит на login настраивается через settings.rate_limit_login (напр. "5/15minutes").
Redis обеспечивает общий счётчик между API workers; в тестах limiter отключается.
"""
import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.security import decode_token

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    enabled=True,
)

# Лимит запуска выгрузок (каталог §16 п.16, PDF-заявка §16 п.25): 10/час
# на пользователя, общий для всех экспорт-эндпоинтов.
EXPORT_RATE_LIMIT = "10/hour"

# Публичная SEO-витрина (§16 п.29): 60 запросов/мин на IP (без авторизации —
# ключ по умолчанию get_remote_address, как у login).
PUBLIC_RATE_LIMIT = "60/minute"


def export_rate_key(request) -> str:
    """Ключ лимита экспорта — id пользователя из access-JWT (без похода в БД).

    slowapi резолвит key_func до тела эндпоинта; неавторизованные попытки
    (нет/битый токен) считаются по IP — как у login.
    """
    auth = request.headers.get("Authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    token = token or request.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            if payload.get("type") == "access" and payload.get("sub"):
                return f"user:{payload['sub']}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)
