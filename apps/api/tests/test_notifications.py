"""Тесты рассылки уведомлений (Telegram). См. ARCHITECTURE_PLAN.md §20.

Тесты синхронные: send_telegram — sync-обёртка, которая зовёт asyncio.run(...).
Внутри async-теста asyncio.run нельзя вызвать (уже работающий loop pytest-asyncio),
поэтому проверяем sync-обёртку из sync-теста (БД здесь не нужна). Стиль — как у
``TestConverter`` в test_import_csv.py: sync-тесты мирно сосуществуют с autouse
async-фикстурой _truncate_tables.
"""
import httpx
import pytest

import app.tasks.notifications as notif_task


class TestSendTelegram:
    def test_send_telegram_success(self, monkeypatch):
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "tok")
        called: dict = {}

        async def _fake(chat_id, text):
            called["args"] = (chat_id, text)
            return {"status": "ok", "chat_id": chat_id}

        monkeypatch.setattr(notif_task, "_send_telegram", _fake)

        assert notif_task.send_telegram("111", "hi") == {"status": "ok", "chat_id": "111"}
        assert called["args"] == ("111", "hi")

    def test_disabled_without_token(self, monkeypatch):
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "")
        calls: list = []

        async def _fake(chat_id, text):
            calls.append((chat_id, text))
            return {"status": "ok"}

        monkeypatch.setattr(notif_task, "_send_telegram", _fake)

        assert notif_task.send_telegram("111", "hi") == {"status": "disabled"}
        assert calls == []

    def test_disabled_without_chat_id(self, monkeypatch):
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "tok")
        calls: list = []

        async def _fake(chat_id, text):
            calls.append((chat_id, text))
            return {"status": "ok"}

        monkeypatch.setattr(notif_task, "_send_telegram", _fake)

        assert notif_task.send_telegram("", "hi") == {"status": "disabled"}
        assert calls == []

    def test_network_error_propagates(self, monkeypatch):
        # Подтверждает, что исключение не глотается (для глобального autoretry).
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "tok")

        async def _raises(chat_id, text):
            raise httpx.HTTPError("boom")

        monkeypatch.setattr(notif_task, "_send_telegram", _raises)

        with pytest.raises(httpx.HTTPError):
            notif_task.send_telegram("111", "hi")

    def test_429_honors_retry_after(self, monkeypatch):
        """429 → self.retry(countdown=retry_after) вместо слепого backoff (FP-13)."""
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "tok")

        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.telegram.org/botX/sendMessage"),
            json={"parameters": {"retry_after": 7}},
        )

        async def _raises(chat_id, text):
            raise httpx.HTTPStatusError("too many", request=resp.request, response=resp)

        monkeypatch.setattr(notif_task, "_send_telegram", _raises)

        # self.retry() перекрыт на инстансе задачи: celery-задача — синглтон,
        # наш фейк просто фиксирует countdown, которым Celery отложит задачу.
        retries: list = []

        def _fake_retry(*, countdown=0, exc=None):
            retries.append(countdown)
            raise RuntimeError("retry")

        monkeypatch.setattr(notif_task.send_telegram, "retry", _fake_retry)

        with pytest.raises(RuntimeError):
            notif_task.send_telegram("111", "hi")
        assert retries == [7]

    def test_429_without_parameters_falls_back_to_1s(self, monkeypatch):
        """429 без parameters.retry_after → минимум 1с, не raw backoff."""
        monkeypatch.setattr(notif_task.settings, "telegram_bot_token", "tok")

        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.telegram.org/botX/sendMessage"),
            json={},
        )

        async def _raises(chat_id, text):
            raise httpx.HTTPStatusError("too many", request=resp.request, response=resp)

        monkeypatch.setattr(notif_task, "_send_telegram", _raises)

        retries: list = []

        def _fake_retry(*, countdown=0, exc=None):
            retries.append(countdown)
            raise RuntimeError("retry")

        monkeypatch.setattr(notif_task.send_telegram, "retry", _fake_retry)

        with pytest.raises(RuntimeError):
            notif_task.send_telegram("111", "hi")
        assert retries == [1]
