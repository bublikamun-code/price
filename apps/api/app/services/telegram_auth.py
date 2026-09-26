"""Связка Telegram-аккаунта с учётной записью портала (§16 п.27, §20).

Поток привязки: клиент в веб-кабинете (Профиль → Telegram) получает
одноразовый код и отправляет его боту командой ``/start <код>``; бот вызывает
``bind_by_code`` — портал запоминает ``telegram_id`` (chat id) пользователя,
после чего клиентские уведомления (дайджест цен, статусы заявок) доставляются
в Telegram (§20).

Redis-ключи:
  ``tg:link:{code}``     → str(user_id), TTL 900 сек — сам код;
  ``tg:linku:{user_id}`` → code, TTL 900 сек — обратный индекс «один активный
  код на пользователя»: повторная генерация удаляет прежний код;
  ``tg:linktry:{scope}`` → счётчик неудачных вводов кода (scope = telegram_id
  входа в Mini App), TTL как у кода.

Привязка вызывается из автономного bot-процесса, поэтому сессия БД
открывается внутри функции (``AsyncSessionLocal``); тесты подменяют
``AsyncSessionLocal`` и ``_get_redis``.
"""
from __future__ import annotations

import secrets
import uuid

import redis as redis_lib

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.repositories import users as users_repo

log = get_logger("app.services.telegram_auth")

LINK_CODE_TTL_SEC = 900  # 15 минут на привязку
# 8 цифр вместо 6: ключевое пространство 10^6 → 10^8. Перебор ограничен и
# лимитом эндпоинта, но короткий код — это ещё и возможность угадать код жертвы
# до истечения TTL. Формат ввода в Mini App: pages/m/index.vue проверяет ^\d{8}$.
LINK_CODE_LENGTH = 8
# Сколько кодов один Telegram-аккаунт может перебрать за окно TTL. Счётчик
# ведём по telegram_id, а не по коду: неверный код не создаёт ключа в Redis, и
# счётчик «по коду» просто копил бы мусор, не ограничивая перебор.
LINK_CODE_MAX_ATTEMPTS = 5

_redis_client: redis_lib.Redis | None = None


class LinkCodeRateLimited(ValueError):
    """Исчерпан лимит попыток ввода кода для одного Telegram-аккаунта."""


def _get_redis() -> redis_lib.Redis:
    """Ленивый sync-клиент Redis (по образцу ``_get_lock_client`` в tasks).

    Отдельный атрибут модуля — тесты подменяют ``_get_redis`` на фейк.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


def _link_key(code: str) -> str:
    return f"tg:link:{code}"


def _user_key(user_id: uuid.UUID) -> str:
    return f"tg:linku:{user_id}"


def _attempts_key(scope: str) -> str:
    return f"tg:linktry:{scope}"


def _register_failed_attempt(client: redis_lib.Redis, scope: str) -> int:
    """Считаем неудачные попытки в рамках одного scope (telegram_id)."""
    attempts = client.incr(_attempts_key(scope))
    client.expire(_attempts_key(scope), LINK_CODE_TTL_SEC)
    log.warning("tg.link_code_failed", scope=scope, attempts=attempts)
    return attempts


def generate_link_code(user_id: uuid.UUID) -> dict:
    """Одноразовый код связки Telegram — один активный код на пользователя.

    Сигнатура и ответ зафиксированы контрактом ``POST /auth/telegram/link-code``
    (``TelegramLinkCodeOut``): ``{"code": str, "expires_in": int}``.
    """
    client = _get_redis()
    # Повторная генерация: прежний код удаляем — активный всегда один.
    old_code = client.get(_user_key(user_id))
    if old_code:
        client.delete(_link_key(old_code))
    code = "".join(secrets.choice("0123456789") for _ in range(LINK_CODE_LENGTH))
    client.set(_link_key(code), str(user_id), ex=LINK_CODE_TTL_SEC)
    client.set(_user_key(user_id), code, ex=LINK_CODE_TTL_SEC)
    log.info("tg.link_code_generated", user_id=str(user_id))
    return {"code": code, "expires_in": LINK_CODE_TTL_SEC}


def consume_link_code(code: str, throttle_scope: str | None = None) -> uuid.UUID | None:
    """Одноразово снять код (GETDEL) → user_id. None — кода нет/истёк.

    Для входа из Mini App: подписанные initData дают telegram_id, код связывает
    его с аккаунтом портала.

    ``throttle_scope`` (telegram_id вызывающего) ограничивает перебор: после
    ``LINK_CODE_MAX_ATTEMPTS`` неудачных вводов дальнейшие попытки этого
    Telegram-аккаунта отклоняются до истечения окна. Без scope функция
    работает как раньше — так вызывается бот, у него своя защита.
    """
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    client = _get_redis()
    user_id_str = client.getdel(_link_key(normalized))
    if not user_id_str:
        if throttle_scope:
            attempts = _register_failed_attempt(client, throttle_scope)
            if attempts >= LINK_CODE_MAX_ATTEMPTS:
                raise LinkCodeRateLimited(
                    f"Слишком много попыток ввода кода. Повторите через "
                    f"{LINK_CODE_TTL_SEC // 60} минут."
                )
        return None
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return None
    # Успех — лимит попыток этого аккаунта сбрасываем, чтобы человеку с
    # опечаткой не пришлось ждать окно после верного кода.
    if throttle_scope:
        client.delete(_attempts_key(throttle_scope))
    client.delete(_user_key(user_id))
    return user_id


async def bind_by_code(code: str, chat_id: int) -> User:
    """Привязать chat_id к пользователю по одноразовому коду (§20).

    Код достаётся и удаляется атомарно (GETDEL) — одноразовый. Если у
    пользователя уже привязан этот же chat_id — идемпотентный успех.
    Ошибки — ``ValueError`` с понятным сообщением (его показывает бот).
    """
    normalized = (code or "").strip().upper()
    if not normalized:
        raise ValueError("Код не передан. Сгенерируйте его в Профиле → Telegram.")

    user_id_str = _get_redis().getdel(_link_key(normalized))
    if not user_id_str:
        raise ValueError(
            "Код не найден или истёк. Сгенерируйте новый в Профиле → Telegram."
        )
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise ValueError(
            "Код повреждён. Сгенерируйте новый в Профиле → Telegram."
        ) from exc

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise ValueError("Пользователь не найден. Обратитесь в поддержку.")
        if user.telegram_id == chat_id:
            # Уже привязан к этому чату — успех без изменений (идемпотентность).
            return user
        if user.telegram_id is not None:
            raise ValueError(
                "Аккаунт уже привязан к другому чату. Сначала отвяжите его (/unlink)."
            )
        other = await users_repo.get_by_telegram_id(db, chat_id)
        if other is not None:
            raise ValueError("Этот чат уже привязан к другому аккаунту портала.")
        user.telegram_id = chat_id
        await db.commit()
        await db.refresh(user)

    log.info("tg.linked", user_id=str(user_id), chat_id=chat_id)
    return user


async def unbind_by_chat(chat_id: int) -> bool:
    """Отвязать чат: обнулить telegram_id пользователя с этим chat_id (§20).

    True — привязка была и снята; False — этот чат никого не привязан.
    """
    async with AsyncSessionLocal() as db:
        user = await users_repo.get_by_telegram_id(db, chat_id)
        if user is None:
            return False
        user.telegram_id = None
        await db.commit()

    log.info("tg.unlinked", chat_id=chat_id)
    return True
