"""Telegram Mini App: вход по подписанным initData (§16 п.27).

POST /api/m/v1/auth/telegram ``{"init_data": str, "link_code": str = ""}``:

1. Верификация подписи initData — HMAC-SHA256, секрет =
   HMAC("WebAppData", bot_token) (официальный алгоритм Telegram), плюс
   проверка свежести ``auth_date`` (анти-replay). Подделка/повтор → 401.
2. Пользователь ищется по ``telegram_id`` из initData:
   - найден и активен → сессия (2FA не запрашивается: подписанные Telegram
     initData — фактор владения аккаунтом Telegram, §16 п.27);
   - не найден + передан ``link_code`` (6 цифр из веб-профиля) → разовая
     привязка ``telegram_id`` к этому аккаунту и сессия;
   - иначе 401 (регистрация — только через менеджера).

Уведомления портала (§20.3) доставляются в этот Telegram-чат автоматически.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import urllib.parse
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import _client_ip, _set_auth_cookies
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.user import User
from app.repositories import users as users_repo
from app.schemas.auth import TokenPair
from app.services.auth import AuthService
from app.services.telegram_auth import consume_link_code

log = get_logger("app.api.miniapp")

router = APIRouter(prefix="/m/v1", tags=["miniapp"])

_INITDATA_TTL_SEC = 3600  # initData старше часа не принимается (анти-replay)


class MiniAppAuthIn(BaseModel):
    """Тело входа из Mini App: initData из Telegram.WebApp + код связки."""

    init_data: str = ""
    link_code: str = ""


def _parse_init_data(raw: str) -> dict[str, str]:
    """``"a=1&b=2"`` → ``{"a": "1", "b": "2"}`` (значения остаются encoded)."""
    out: dict[str, str] = {}
    for chunk in raw.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        out[key] = value
    return out


def _verify_init_data(raw: str) -> int:
    """Проверить подпись/свежесть initData → telegram user id.

    Алгоритм Telegram: data_check_string = отсортированные ``k=v`` (кроме
    hash) через ``\\n``; secret = HMAC("WebAppData", bot_token);
    hash = HMAC(secret, data_check_string), сравнение constant-time.
    """
    if not settings.telegram_bot_token:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Telegram не сконфигурирован на сервере",
        )
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "initData не передан")

    pairs = _parse_init_data(raw)
    received_hash = pairs.get("hash", "")
    data_check = "\n".join(
        f"{k}={v}" for k, v in sorted(pairs.items()) if k != "hash"
    )
    secret = hmac_lib.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac_lib.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac_lib.compare_digest(calculated, received_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Подпись initData недействительна")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Некорректный auth_date") from exc
    if auth_date < time.time() - _INITDATA_TTL_SEC:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Данные входа устарели — переоткройте Mini App",
        )

    try:
        tg_user = json.loads(urllib.parse.unquote(pairs.get("user", "{}")))
        return int(tg_user["id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "В initData нет пользователя Telegram"
        ) from exc


@router.post("/auth/telegram", response_model=TokenPair)
@limiter.limit(settings.rate_limit_login)
async def telegram_auth(
    request: Request,
    body: MiniAppAuthIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Вход в Mini App по initData (+ привязка по коду, если аккаунт ещё не связан)."""
    tg_user_id = _verify_init_data(body.init_data)

    user = await users_repo.get_by_telegram_id(db, tg_user_id)
    if user is None and body.link_code.strip():
        user_id = consume_link_code(body.link_code)
        if user_id is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Код не найден или истёк. Получите новый: веб-кабинет → Профиль → Telegram.",
            )
        linked = await db.get(User, user_id)
        if linked is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
        if linked.telegram_id is not None and linked.telegram_id != tg_user_id:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Аккаунт уже привязан к другому Telegram. Сначала отвяжите его в профиле.",
            )
        linked.telegram_id = tg_user_id
        await db.flush()
        user = linked
        log_info = {"linked": True}
    else:
        log_info = {"linked": False}

    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Telegram-аккаунт не привязан. Получите код: веб-кабинет → Профиль → Telegram.",
        )

    tokens = await AuthService(db).login_miniapp(
        user, request.headers.get("user-agent"), _client_ip(request)
    )
    _set_auth_cookies(response, tokens)
    log.info("auth.login_miniapp", user_id=str(user.id), tg_user_id=tg_user_id, **(log_info or {}))
    return tokens
