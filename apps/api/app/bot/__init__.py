"""Telegram-бот — пакет точки входа (`python -m app.bot`, §9, §20).

Реализация long-polling бота — в ``__main__.py`` (/start, /id, /help).
Задачи отправки сообщений живут отдельно: ``app.tasks.notifications.send_telegram``.
"""
