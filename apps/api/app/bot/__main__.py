"""Точка входа Telegram-бота: `python -m app.bot` (long polling).

Рабочий бот (§20): /start [<код>], /unlink, /id, /help. Служит трём целям:
1) привязка аккаунта клиента: код из Профиля → Telegram отправляется боту
   командой ``/start <код>`` — ``services.telegram_auth.bind_by_code``
   запоминает chat_id, после чего клиентские уведомления (дайджест цен,
   статусы заявок) доставляются в этот чат;
2) менеджер узнаёт chat id своего чата (/id) — его нужно вписать в
   TELEGRAM_MANAGER_CHAT_ID (.env), после чего задачи send_telegram
   (сводки о прайсах/заявках) начнут доставляться;
3) контейнер `bot` живой и не в crash-loop.
HTTP — httpx (как в tasks/notifications.py), без новых зависимостей.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import threading

import httpx

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.services import telegram_auth

TG_API = "https://api.telegram.org"
POLL_TIMEOUT_SEC = 25  # long polling
REQUEST_TIMEOUT_SEC = 35  # > POLL_TIMEOUT_SEC

# httpx логирует URL запросов целиком, а он содержит токен бота — глушим.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = get_logger("app.bot")
_stop = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    log.info("bot.signal", signum=signum)
    _stop.set()


def _call(client: httpx.Client, method: str, **payload: object) -> dict:
    resp = client.post(
        f"{TG_API}/bot{settings.telegram_bot_token}/{method}",
        json=payload,
    )
    resp.raise_for_status()
    data: dict = resp.json()
    return data


def _reply(client: httpx.Client, chat_id: int | str, text: str) -> None:
    try:
        _call(client, "sendMessage", chat_id=chat_id, text=text)
    except httpx.HTTPError as exc:
        log.warning("bot.send_failed", chat_id=chat_id, error=str(exc))


def _bind_account(client: httpx.Client, chat_id: int, code: str) -> None:
    """Привязка аккаунта по коду: bot-процесс автономный — свой цикл событий."""
    try:
        user = asyncio.run(telegram_auth.bind_by_code(code, chat_id))
    except ValueError as exc:
        _reply(client, chat_id, f"Не удалось привязать аккаунт ❌\n{exc}")
        return
    except Exception:
        log.exception("bot.bind_failed", chat_id=chat_id)
        _reply(
            client,
            chat_id,
            "Не удалось привязать аккаунт ❌\n"
            "Внутренняя ошибка — попробуйте позже.",
        )
        return
    _reply(
        client,
        chat_id,
        "Аккаунт привязан ✅\n"
        f"Аккаунт: {user.email}\n\n"
        "Уведомления портала будут приходить в этот чат. "
        "Отвязать: /unlink",
    )


def _unlink_account(client: httpx.Client, chat_id: int) -> None:
    """Отвязка чата от аккаунта: bot-процесс автономный — свой цикл событий."""
    try:
        unbound = asyncio.run(telegram_auth.unbind_by_chat(chat_id))
    except Exception:
        log.exception("bot.unbind_failed", chat_id=chat_id)
        _reply(
            client,
            chat_id,
            "Не удалось отвязать аккаунт ❌ Попробуйте позже.",
        )
        return
    if unbound:
        _reply(
            client,
            chat_id,
            "Аккаунт отвязан ✅ Уведомления больше не будут приходить в этот чат.",
        )
    else:
        _reply(client, chat_id, "Этот чат не привязан к аккаунту портала.")


def _handle_update(client: httpx.Client, update: dict) -> None:
    message = update.get("message")
    if not message:
        return  # edited_message, callback_query и пр. — не наша забота
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    log.info("bot.message", chat_id=chat_id, text=text[:64])

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start":
        if arg:
            _bind_account(client, chat_id, arg)
        else:
            _reply(
                client,
                chat_id,
                "Здравствуйте! Это бот B2B-портала «Свет в доме».\n\n"
                f"Ваш chat id: {chat_id}\n\n"
                "Привязка аккаунта (клиенты): в личном кабинете откройте "
                "Профиль → Telegram → «Сгенерировать код связки», затем "
                "отправьте боту команду:\n"
                "/start <код>\n\n"
                "После привязки уведомления о ценах и статусах заявок будут "
                "приходить в этот чат. Если вы менеджер — впишите этот id в "
                "TELEGRAM_MANAGER_CHAT_ID (.env), чтобы получать сводки "
                "портала.\n\n"
                "Команды: /help",
            )
    elif cmd == "/unlink":
        _unlink_account(client, chat_id)
    elif cmd == "/id":
        _reply(client, chat_id, f"chat id этого чата: {chat_id}")
    elif cmd == "/help":
        _reply(
            client,
            chat_id,
            "Команды:\n"
            "/start — приветствие и ваш chat id\n"
            "/start <код> — привязать аккаунт портала "
            "(код из Профиля → Telegram)\n"
            "/unlink — отвязать этот чат от аккаунта\n"
            "/id — chat id этого чата\n"
            "/help — эта справка",
        )
    # Прочий текст игнорируем молча: бот не диалоговый.


def main() -> int:
    setup_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not settings.telegram_bot_token:
        # Как и раньше: без токена процесс живой, но бесполезный — чтобы
        # restart-политика compose не устроила цикл перезапусков.
        log.warning("bot.no_token — TELEGRAM_BOT_TOKEN пуст, long polling не запущен")
        _stop.wait()
        return 0

    offset = 0
    with httpx.Client(timeout=REQUEST_TIMEOUT_SEC) as client:
        me = _call(client, "getMe")
        log.info(
            "bot.started",
            username=(me.get("result") or {}).get("username"),
            polling_timeout=POLL_TIMEOUT_SEC,
        )
        while not _stop.is_set():
            try:
                data = _call(client, "getUpdates", offset=offset, timeout=POLL_TIMEOUT_SEC)
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    _handle_update(client, update)
            except httpx.HTTPError as exc:
                if not _stop.is_set():
                    log.warning("bot.poll_error", error=str(exc))
                    _stop.wait(3)

    log.info("bot.stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
