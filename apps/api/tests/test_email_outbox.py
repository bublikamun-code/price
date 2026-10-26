"""NOTIF-01: durable-очередь email_outbox — идемпотентность и свипер.

Слои:
  1. ``send_email(outbox_id=...)`` — успех → SENT (повторный вызов не шлёт),
     нет SMTP-транспорта → SKIPPED, SMTP-ошибка → attempts/last_error,
     исчерпание ретраев → FAILED;
  2. ``requeue_stuck_emails`` — только старые PENDING реэнквитятся
     («аренда» через updated_at), SENT/FAILED/свежие — нет;
  3. beat-расписание зарегистрировано (паттерн test_import_reliability).

Фейки SMTP/логгера/Celery-задач переиспользуются из
test_notification_dispatch_idempotency (одинаковая семантика).
"""
import asyncio
import smtplib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.tasks.email as email_task
from app.models.system import EmailOutbox
from tests.test_notification_dispatch_idempotency import _FakeCeleryTask, _FakeSMTP, _LogSpy

# ----------------------------- helpers -----------------------------


async def _make_row(
    session_factory,
    *,
    status: str = EmailOutbox.STATUS_PENDING,
    updated_at: datetime | None = None,
    attempts: int = 0,
) -> EmailOutbox:
    async with session_factory() as s:
        row = EmailOutbox(
            to="user@example.by",
            subject="Тема",
            html_body="<p>body</p>",
            status=status,
            attempts=attempts,
            updated_at=updated_at or datetime.now(UTC),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


def _configure_smtp(monkeypatch):
    monkeypatch.setattr(email_task.settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(email_task.settings, "smtp_port", 587)
    monkeypatch.setattr(email_task.settings, "smtp_user", "noreply@test")
    monkeypatch.setattr(email_task.settings, "smtp_password", "secret")
    monkeypatch.setattr(email_task.settings, "smtp_from", "noreply@test")
    monkeypatch.setattr(email_task.settings, "smtp_tls", True)


# ===========================================================================
# 1. send_email(outbox_id=...): идемпотентность и финализация статуса
# ===========================================================================
class TestSendEmailOutbox:
    async def test_success_marks_sent_and_is_idempotent(
        self, session_factory, monkeypatch
    ):
        """Успех → SENT; повторный вызов (re-delivery acks_late) не шлёт снова."""
        row = await _make_row(session_factory)
        monkeypatch.setattr(email_task, "_worker_session", session_factory)
        _configure_smtp(monkeypatch)
        monkeypatch.setattr(email_task.smtplib, "SMTP", _FakeSMTP)
        _FakeSMTP.instances.clear()

        # Celery-обёртка зовёт asyncio.run — из теста её нужно выносить в поток
        # (канон проекта, см. test_notification_dispatch_idempotency).
        first = await asyncio.to_thread(email_task.send_email.run, outbox_id=str(row.id))
        assert first["status"] == "ok"
        assert len(_FakeSMTP.instances) == 1

        second = await asyncio.to_thread(email_task.send_email.run, outbox_id=str(row.id))
        assert second["status"] == "already_sent"
        assert len(_FakeSMTP.instances) == 1  # повторной SMTP-сессии не было

        async with session_factory() as s:
            final = await s.get(EmailOutbox, row.id)
            assert final.status == EmailOutbox.STATUS_SENT
            assert final.attempts == 1
            assert final.last_error is None

    async def test_no_transport_marks_skipped(self, session_factory, monkeypatch):
        """Нет SMTP-транспорта → SKIPPED (терминальный; свипер не тронет)."""
        row = await _make_row(session_factory)
        monkeypatch.setattr(email_task, "_worker_session", session_factory)
        monkeypatch.setattr(email_task.settings, "smtp_host", "")
        spy = _LogSpy()
        monkeypatch.setattr(email_task, "log", spy)

        res = await asyncio.to_thread(email_task.send_email.run, outbox_id=str(row.id))

        assert res == {"status": "skipped", "reason": "no_transport", "to": "user@example.by"}
        assert any("email.skipped_no_transport" in ev for ev, _ in spy.warnings)
        async with session_factory() as s:
            final = await s.get(EmailOutbox, row.id)
            assert final.status == EmailOutbox.STATUS_SKIPPED

    async def test_smtp_error_records_attempt_and_retries_exhaust_to_failed(
        self, session_factory, monkeypatch
    ):
        """SMTP-ошибка → attempts+1/last_error; последняя попытка → FAILED."""
        row = await _make_row(session_factory)
        monkeypatch.setattr(email_task, "_worker_session", session_factory)
        _configure_smtp(monkeypatch)

        class _BrokenSMTP:
            def __init__(self, *args, **kwargs):
                raise smtplib.SMTPServerDisconnected("connection lost")

        monkeypatch.setattr(email_task.smtplib, "SMTP", _BrokenSMTP)

        # Первая попытка вне цикла autoretry: статус остаётся PENDING
        # (остались ретраи), попытка и ошибка зафиксированы.
        with pytest.raises(smtplib.SMTPServerDisconnected):
            await asyncio.to_thread(email_task.send_email.run, outbox_id=str(row.id))
        async with session_factory() as s:
            after_first = await s.get(EmailOutbox, row.id)
            assert after_first.status == EmailOutbox.STATUS_PENDING
            assert after_first.attempts == 1
            assert "connection lost" in after_first.last_error

        # Исчерпание ретраев (eager apply с retries=max_retries): FAILED.
        res = await asyncio.to_thread(
            email_task.send_email.apply, kwargs={"outbox_id": str(row.id)}, retries=3
        )
        assert res.state == "FAILURE"
        async with session_factory() as s:
            final = await s.get(EmailOutbox, row.id)
            assert final.status == EmailOutbox.STATUS_FAILED
            assert final.attempts == 2
            assert "connection lost" in final.last_error

    async def test_missing_outbox_row_is_skipped(self, session_factory, monkeypatch):
        """Строка удалена, а задача осталась: отправлять нечего — не ошибка."""
        monkeypatch.setattr(email_task, "_worker_session", session_factory)
        res = await asyncio.to_thread(email_task.send_email.run, outbox_id=str(uuid.uuid4()))
        assert res["status"] == "skipped"
        assert res["reason"] == "outbox_missing"

    def test_legacy_kwargs_still_supported(self, monkeypatch):
        """Legacy-формат (to/subject/html_body) — для задач в очереди на момент деплоя."""
        _configure_smtp(monkeypatch)
        monkeypatch.setattr(email_task.smtplib, "SMTP", _FakeSMTP)
        _FakeSMTP.instances.clear()

        res = email_task.send_email.run(
            to="legacy@example.by", subject="Тема", html_body="<p>x</p>"
        )
        assert res["status"] == "ok"
        assert _FakeSMTP.instances[-1].msg["To"] == "legacy@example.by"


# ===========================================================================
# 2. requeue_stuck_emails: свипер зависших PENDING
# ===========================================================================
class TestRequeueStuckEmails:
    async def test_only_old_pending_requeued(self, session_factory, monkeypatch):
        old_pending = await _make_row(
            session_factory,
            updated_at=datetime.now(UTC) - timedelta(minutes=11),
        )
        await _make_row(session_factory)  # свежий PENDING — не реэнквитится
        await _make_row(
            session_factory,
            status=EmailOutbox.STATUS_SENT,
            updated_at=datetime.now(UTC) - timedelta(minutes=11),
        )
        await _make_row(
            session_factory,
            status=EmailOutbox.STATUS_FAILED,
            updated_at=datetime.now(UTC) - timedelta(minutes=11),
        )

        fake = _FakeCeleryTask()
        monkeypatch.setattr(email_task, "_worker_session", session_factory)
        monkeypatch.setattr(email_task, "send_email", fake)

        result = await email_task._requeue_stuck()

        assert result == {"status": "ok", "requeued": 1}
        assert [c["outbox_id"] for c in fake.calls] == [str(old_pending.id)]
        # «Аренда»: updated_at сдвинут — следующий свип не раньше, чем через 10 мин.
        async with session_factory() as s:
            bumped = await s.get(EmailOutbox, old_pending.id)
            assert bumped.updated_at > old_pending.updated_at
            assert bumped.status == EmailOutbox.STATUS_PENDING

        # Повторный свип сразу после аренды — ничего не реэнквитит (идемпотентность).
        assert await email_task._requeue_stuck() == {"status": "ok", "requeued": 0}
        assert len(fake.calls) == 1

    def test_beat_schedule_registered(self):
        entry = email_task.celery_app.conf.beat_schedule.get("requeue-stuck-emails")
        assert entry is not None
        assert entry["task"] == "app.tasks.email.requeue_stuck_emails"
        assert entry["schedule"] == 300.0
