"""Telegram-бот — точка входа (`python -m app.bot`).

См. ARCHITECTURE_PLAN.md §9, §20. Реализуется на Этапе 6.
Пока — заглушка, чтобы контейнер `bot` стартовал без падения.
"""
from app.core.logging import get_logger, setup_logging


def main() -> None:
    setup_logging()
    log = get_logger("app.bot")
    log.info("bot.starting.placeholder")
    # TODO(Этап 6): запустить long-polling (aiogram/telebot) или webhook.
    # Пока держим процесс живым, чтобы контейнер не падал.
    log.warning("bot.not_implemented — процесс спит. Реализовать на Этапе 6.")
    import time
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
