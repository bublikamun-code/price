"""Тесты аудита 2026-09-06: идемпотентность dispatch + ретраи + email-задача.

Слои:
  1. ``dispatch_price_changed`` — идемпотентность re-delivery (Redis SET NX
     ``notif:dispatched:{version_id}``) и autoretry с освобождением ключа при сбое;
  2. ``app.tasks.email.send_email`` — SMTP-отправка, skipped/no_transport, ретраи;
  3. ``services.email.queue_email`` — диспатч Celery-задачи (fire-and-forget);
  4. ``POST /auth/forgot-password`` — 202 + письмо реально ставится в очередь;
  5. TG-доставка клиентам/менеджерам (§20) — дайджест привязанному клиенту,
     broadcast сводки менеджерам по telegram_id (env-чат + привязанные).

Redis-блокировка подменяется in-memory фейком (``_get_lock_client``), SMTP —
фейковым ``smtplib.SMTP``. Целевая задача зовётся через ``asyncio.to_thread``,
т.к. обёртка использует ``asyncio.run`` (канон проекта, см. test_photo_zip).
"""
import asyncio
import smtplib
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import ClassVar

import pytest
from sqlalchemy import select

import app.services.email as email_service
import app.tasks.email as email_task
import app.tasks.notifications as notif_task
from app.core.security import hash_password
from app.models.catalog import PriceHistory, PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus, UserRole
from app.models.system import Notification
from app.models.user import Favorite, User
from tests.conftest import create_brand, create_product, create_user

# ----------------------------- helpers -----------------------------

PASSWORD = "Passw0rd!"


class _FakeLockRedis:
    """In-memory эмуляция Redis SET NX EX / GET / DELETE для lock-помощников."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


@pytest.fixture
def fake_lock(monkeypatch):
    fake = _FakeLockRedis()
    monkeypatch.setattr(notif_task, "_get_lock_client", lambda: fake)
    return fake


class _FakeTg:
    """Фейк Celery-таски send_telegram: записывает вызовы .delay()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def delay(self, chat_id: str, text: str) -> None:
        self.calls.append((chat_id, text))


class _FakeCeleryTask:
    """Фейк Celery-задачи: записывает kwargs вызовов .delay()."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self._fail = fail

    def delay(self, **kwargs):
        if self._fail:
            raise RuntimeError("broker down")
        self.calls.append(kwargs)


class _LogSpy:
    """Подмена structlog-логгера: собирает события по уровням."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []
        self.infos: list[tuple[str, dict]] = []

    def warning(self, event, **kw):
        self.warnings.append((event, kw))

    def info(self, event, **kw):
        self.infos.append((event, kw))

    def exception(self, event, **kw):
        self.warnings.append((event, kw))


class _FakeSMTP:
    """Фейк smtplib.SMTP: контекстный менеджер, записывает вызовы."""

    instances: ClassVar[list["_FakeSMTP"]] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.calls: list = []
        self.msg = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.msg = msg
        self.calls.append("send")


def _make_fake_diff():
    """Фейковый VersionDiff (поля см. price_changed_manager.j2 + tasks/notifications)."""
    return SimpleNamespace(
        changed=[{"sku": "A"}],
        count_up=1,
        count_down=0,
        count_new=0,
        count_override_reset=0,
        count_unchanged=0,
    )


def _make_fake_recipient(user_id, telegram_id=None):
    return SimpleNamespace(
        user_id=user_id,
        affected=[
            SimpleNamespace(sku="A", name="Widget", delta_percent=10.0, category="up")
        ],
        telegram_id=telegram_id,
    )


async def _make_version(sf, *, manager, filename="p.csv") -> PriceListVersion:
    async with sf() as s:
        v = PriceListVersion(
            uploaded_by=manager.id,
            filename=filename,
            import_mode=ImportMode.UPSERT,
            status=PriceListVersionStatus.DONE,
            base_currency="BYN",
            rate_to_byn=1,
            rate_source="MANUAL",
        )
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


async def _add_history(sf, *, product, version, base) -> None:
    async with sf() as s:
        s.add(
            PriceHistory(
                product_id=product.id,
                base_price=base,
                override_price=None,
                price_list_version_id=version.id,
            )
        )
        await s.commit()


async def _count_notifications(sf) -> list[Notification]:
    async with sf() as s:
        return list((await s.scalars(select(Notification))).all())


async def _make_client(sf, *, email):
    async with sf() as s:
        u = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            full_name=email.split("@")[0].title(),
            role=UserRole.CLIENT,
            is_active=True,
            price_digest_enabled=True,
            price_digest_sources=["favorite"],
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


# ===========================================================================
# 1. dispatch_price_changed: идемпотентность re-delivery
# ===========================================================================
class TestDispatchIdempotency:
    async def test_re_delivery_does_not_duplicate_notifications(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Повторная доставка задачи (acks_late) не создаёт дублей уведомлений."""
        mgr = await create_user(session_factory, email="m10@x.by", role=UserRole.MANAGER)
        u1 = await _make_client(session_factory, email="c10@x.by")
        brand = await create_brand(session_factory, name="B10")
        prod = await create_product(
            session_factory, sku="A", name="Widget", brand=brand, base_price=100
        )
        v_new = await _make_version(session_factory, manager=mgr, filename="new.csv")
        await _add_history(session_factory, product=prod, version=v_new, base=Decimal("110.00"))
        async with session_factory() as s:
            s.add(Favorite(user_id=u1.id, product_id=prod.id))
            await s.commit()

        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)
        # стабы обязаны быть async: задача их await-ит (как реальные сервисы)
        async def fake_diff(db, version_id):
            return _make_fake_diff()

        async def fake_recipients(db, changed):
            return [_make_fake_recipient(u1.id)]

        monkeypatch.setattr(notif_task, "compute_version_diff", fake_diff)
        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_recipients)

        first = await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str(v_new.id)
        )
        assert first["status"] == "ok"

        second = await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str(v_new.id)
        )
        assert second["status"] == "already_dispatched"

        notifs = await _count_notifications(session_factory)
        assert len(notifs) == 2  # PRICE_CHANGED менеджеру + DIGEST клиенту, без дублей
        assert len(fake_tg.calls) == 1  # TG-задача тоже одна

    async def test_lock_released_on_failure_allows_redispatch(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Сбой dispatch освобождает ключ → повторный вызов выполняется заново."""
        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        diff = _make_fake_diff()
        calls = {"n": 0}

        async def flaky_compute(db, version_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return diff

        monkeypatch.setattr(notif_task, "compute_version_diff", flaky_compute)

        async def fake_no_recipients(db, changed):
            return []

        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_no_recipients)

        mgr = await create_user(session_factory, email="m11@x.by", role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="B11")
        prod = await create_product(
            session_factory, sku="A", name="Widget", brand=brand, base_price=100
        )
        v_new = await _make_version(session_factory, manager=mgr)
        await _add_history(session_factory, product=prod, version=v_new, base=Decimal("110.00"))
        vid = str(v_new.id)

        with pytest.raises(RuntimeError):
            await asyncio.to_thread(notif_task.dispatch_price_changed.run, vid)
        assert fake_lock.values == {}  # ключ освобождён — не «отправлено»

        ok = await asyncio.to_thread(notif_task.dispatch_price_changed.run, vid)
        assert ok["status"] == "ok"
        assert calls["n"] == 2  # повторный прогон реально выполнился

        notifs = await _count_notifications(session_factory)
        assert len(notifs) == 1  # одна попытка записи — без дублей
        assert f"notif:dispatched:{vid}" in fake_lock.values  # успех зафиксирован

    def test_lock_key_ttl_and_token(self, fake_lock):
        """Ключ notif:dispatched:{vid}, TTL 7 дней, освобождение только по своему токену."""
        vid = str(uuid.uuid4())
        assert notif_task._try_acquire_dispatch_lock(vid, "token-1") is True
        assert notif_task._try_acquire_dispatch_lock(vid, "token-2") is False

        key = f"notif:dispatched:{vid}"
        assert fake_lock.values[key] == "token-1"
        assert fake_lock.ttls[key] == notif_task._DISPATCH_LOCK_TTL_SEC
        assert notif_task._DISPATCH_LOCK_TTL_SEC == 60 * 60 * 24 * 7

        notif_task._release_dispatch_lock(vid, "token-2")  # чужой токен — ключ жив
        assert key in fake_lock.values
        notif_task._release_dispatch_lock(vid, "token-1")
        assert key not in fake_lock.values


# ===========================================================================
# 2. dispatch_price_changed: ретраи
# ===========================================================================
class TestDispatchRetry:
    def test_retry_config(self):
        t = notif_task.dispatch_price_changed
        assert t.autoretry_for == (Exception,)
        assert t.max_retries == 3
        assert t.retry_backoff

    def test_transient_error_retried_up_to_max(self, monkeypatch, fake_lock):
        """apply() в eager-режиме прогоняет весь цикл autoretry: старт + max_retries."""
        attempts = {"n": 0}

        async def boom(version_id):
            attempts["n"] += 1
            raise RuntimeError("db down")

        monkeypatch.setattr(notif_task, "_dispatch", boom)
        vid = str(uuid.uuid4())

        res = notif_task.dispatch_price_changed.apply(args=[vid])

        assert res.state == "FAILURE"  # после исчерпания ретраев задача падает
        assert attempts["n"] == 1 + 3  # старт + autoretry max_retries=3
        assert fake_lock.values == {}  # ключ освобождён перед каждым ретраем

    def test_fails_after_max_retries(self, monkeypatch, fake_lock):
        async def boom(version_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(notif_task, "_dispatch", boom)
        vid = str(uuid.uuid4())

        res = notif_task.dispatch_price_changed.apply(args=[vid], retries=3)

        assert res.state == "FAILURE"
        assert isinstance(res.result, RuntimeError)
        assert fake_lock.values == {}


# ===========================================================================
# 3. email-задача: SMTP-отправка / skipped / ретраи
# ===========================================================================
class TestSendEmailTask:
    def test_skipped_when_smtp_not_configured(self, monkeypatch):
        monkeypatch.setattr(email_task.settings, "smtp_host", "")
        spy = _LogSpy()
        monkeypatch.setattr(email_task, "log", spy)

        res = email_task.send_email.run(
            to="user@example.by", subject="Сброс пароля", html_body="<p>link</p>"
        )

        assert res["status"] == "skipped"
        assert res["reason"] == "no_transport"
        assert any("email.skipped_no_transport" in ev for ev, _ in spy.warnings)

    def test_sends_via_smtp_with_starttls_login_and_bodies(self, monkeypatch):
        monkeypatch.setattr(email_task.settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(email_task.settings, "smtp_port", 587)
        monkeypatch.setattr(email_task.settings, "smtp_user", "noreply@test")
        monkeypatch.setattr(email_task.settings, "smtp_password", "secret")
        monkeypatch.setattr(email_task.settings, "smtp_from", "noreply@test")
        monkeypatch.setattr(email_task.settings, "smtp_tls", True)
        monkeypatch.setattr(email_task.smtplib, "SMTP", _FakeSMTP)
        _FakeSMTP.instances.clear()

        res = email_task.send_email.run(
            to="user@example.by",
            subject="Сброс пароля",
            html_body="<p>Здравствуйте!</p><p>Ссылка: https://x/reset-password?token=abc</p>",
        )

        assert res["status"] == "ok"
        smtp = _FakeSMTP.instances[-1]
        assert (smtp.host, smtp.port) == ("smtp.test", 587)
        assert "starttls" in smtp.calls
        assert ("login", "noreply@test", "secret") in smtp.calls
        assert "send" in smtp.calls
        assert smtp.msg["To"] == "user@example.by"
        assert smtp.msg["From"] == "noreply@test"
        assert smtp.msg["Subject"] == "Сброс пароля"

        parts = {p.get_content_type(): p for p in smtp.msg.walk()}
        text = parts["text/plain"].get_content()
        html = parts["text/html"].get_content()
        assert "https://x/reset-password?token=abc" in text  # текстовая альтернатива
        assert "<p>" not in text
        assert "https://x/reset-password?token=abc" in html

    def test_smtp_error_retried_up_to_max_then_fails(self, monkeypatch):
        monkeypatch.setattr(email_task.settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(email_task.settings, "smtp_from", "noreply@test")
        monkeypatch.setattr(email_task.settings, "smtp_tls", False)

        counter = {"n": 0}

        class _BrokenSMTP:
            def __init__(self, *args, **kwargs):
                counter["n"] += 1
                raise smtplib.SMTPServerDisconnected("connection lost")

        monkeypatch.setattr(email_task.smtplib, "SMTP", _BrokenSMTP)

        # eager apply прогоняет весь цикл autoretry: старт + max_retries=3.
        res = email_task.send_email.apply(
            args=["user@example.by", "subj", "<p>x</p>"]
        )
        assert res.state == "FAILURE"
        assert counter["n"] == 1 + 3

        # ретраи исчерпаны (request.retries=3) → один прогон без повторов.
        counter["n"] = 0
        res = email_task.send_email.apply(
            args=["user@example.by", "subj", "<p>x</p>"], retries=3
        )
        assert res.state == "FAILURE"
        assert counter["n"] == 1

    def test_email_task_retry_config(self):
        t = email_task.send_email
        assert t.autoretry_for == (Exception,)
        assert t.max_retries == 3
        assert t.retry_backoff


# ===========================================================================
# 4. services.email.queue_email: диспатч в очередь (fire-and-forget)
# ===========================================================================
class TestQueueEmail:
    def test_queue_email_dispatches_task(self, monkeypatch):
        fake = _FakeCeleryTask()
        monkeypatch.setattr(email_service, "send_email", fake)

        email_service.queue_email(
            to="user@example.by", subject="Тема", html_body="<p>body</p>"
        )

        assert fake.calls == [
            {"to": "user@example.by", "subject": "Тема", "html_body": "<p>body</p>"}
        ]

    def test_queue_email_broker_failure_is_swallowed(self, monkeypatch):
        fake = _FakeCeleryTask(fail=True)
        monkeypatch.setattr(email_service, "send_email", fake)
        spy = _LogSpy()
        monkeypatch.setattr(email_service, "log", spy)

        email_service.queue_email(
            to="user@example.by", subject="Тема", html_body="<p>body</p>"
        )  # не бросает

        assert fake.calls == []
        assert any("email.enqueue_failed" in ev for ev, _ in spy.warnings)


# ===========================================================================
# 5. TG-доставка клиентам/менеджерам (§20): дайджест + broadcast менеджерам
# ===========================================================================
class TestTelegramDelivery:
    async def test_digest_sent_to_bound_client(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Клиенту с telegram_id дайджест уходит и in-app, и в Telegram."""
        mgr = await create_user(session_factory, email="m20@x.by", role=UserRole.MANAGER)
        u1 = await _make_client(session_factory, email="c20@x.by")
        async with session_factory() as s:
            u1_tg = await s.get(User, u1.id)
            u1_tg.telegram_id = 424242
            await s.commit()

        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        async def fake_diff(db, version_id):
            return _make_fake_diff()

        async def fake_recipients(db, changed):
            return [_make_fake_recipient(u1.id, telegram_id=424242)]

        monkeypatch.setattr(notif_task, "compute_version_diff", fake_diff)
        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_recipients)

        res = await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str((await _make_version(session_factory, manager=mgr)).id)
        )
        assert res["status"] == "ok"

        notifs = await _count_notifications(session_factory)
        digest = next(n for n in notifs if n.type == "PRICE_CHANGED_DIGEST")
        assert "inapp" in digest.channel and "telegram" in digest.channel

        # TG клиенту: chat_id из recipient.telegram_id, текст = тело дайджеста.
        assert ("424242", digest.body) in fake_tg.calls
        # TG менеджеру: env-чат + сводка менеджера (не дайджест).
        assert any(chat == "999" for chat, _ in fake_tg.calls)
        assert sum(1 for chat, _ in fake_tg.calls if chat == "424242") == 1

    async def test_digest_not_sent_without_telegram(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Клиент без telegram_id получает только in-app (без TG-задачи)."""
        mgr = await create_user(session_factory, email="m21@x.by", role=UserRole.MANAGER)
        u1 = await _make_client(session_factory, email="c21@x.by")

        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        async def fake_diff(db, version_id):
            return _make_fake_diff()

        async def fake_recipients(db, changed):
            return [_make_fake_recipient(u1.id, telegram_id=None)]

        monkeypatch.setattr(notif_task, "compute_version_diff", fake_diff)
        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_recipients)

        res = await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str((await _make_version(session_factory, manager=mgr)).id)
        )
        assert res["status"] == "ok"

        notifs = await _count_notifications(session_factory)
        digest = next(n for n in notifs if n.type == "PRICE_CHANGED_DIGEST")
        assert digest.channel == ["inapp"]
        assert fake_tg.calls == []

    async def test_summary_sent_to_bound_managers(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Сводка уходит в env-чат и всем MANAGER с привязанным telegram_id."""
        mgr = await create_user(session_factory, email="m22@x.by", role=UserRole.MANAGER)
        mgr2 = await create_user(session_factory, email="m23@x.by", role=UserRole.MANAGER)
        async with session_factory() as s:
            m2 = await s.get(User, mgr2.id)
            m2.telegram_id = 31337
            await s.commit()

        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        async def fake_diff(db, version_id):
            return _make_fake_diff()

        async def fake_no_recipients(db, changed):
            return []

        monkeypatch.setattr(notif_task, "compute_version_diff", fake_diff)
        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_no_recipients)

        res = await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str((await _make_version(session_factory, manager=mgr)).id)
        )
        assert res["status"] == "ok"

        chats = sorted(chat for chat, _ in fake_tg.calls)
        assert chats == ["31337", "999"]  # env-чат + привязанный менеджер
        # Текст везде — менеджерская сводка (одинаковая).
        assert len({text for _, text in fake_tg.calls}) == 1

    async def test_env_chat_not_duplicated_when_manager_bound_to_it(
        self, session_factory, monkeypatch, fake_lock
    ):
        """Если привязанный менеджер сидит в env-чате — сообщение не дублируется."""
        mgr = await create_user(session_factory, email="m24@x.by", role=UserRole.MANAGER)
        async with session_factory() as s:
            m = await s.get(User, mgr.id)
            m.telegram_id = 999
            await s.commit()

        monkeypatch.setattr(notif_task, "_worker_session", session_factory)
        monkeypatch.setattr(notif_task.settings, "telegram_manager_chat_id", "999")
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)

        async def fake_diff(db, version_id):
            return _make_fake_diff()

        async def fake_no_recipients(db, changed):
            return []

        monkeypatch.setattr(notif_task, "compute_version_diff", fake_diff)
        monkeypatch.setattr(notif_task, "find_digest_recipients", fake_no_recipients)

        await asyncio.to_thread(
            notif_task.dispatch_price_changed.run, str((await _make_version(session_factory, manager=mgr)).id)
        )
        assert [chat for chat, _ in fake_tg.calls] == ["999"]  # один раз


# ===========================================================================
# 6. POST /auth/forgot-password: 202 + письмо ставится в очередь
# ===========================================================================
class TestForgotPasswordDispatch:
    async def test_forgot_password_202_and_email_dispatched(
        self, api_client, session_factory, monkeypatch
    ):
        await create_user(
            session_factory, email="reset@x.by", role=UserRole.CLIENT, password=PASSWORD
        )
        fake = _FakeCeleryTask()
        monkeypatch.setattr(email_service, "send_email", fake)

        resp = await api_client.post(
            "/api/v1/auth/forgot-password", json={"email": "reset@x.by"}
        )

        assert resp.status_code == 202
        assert len(fake.calls) == 1
        assert fake.calls[0]["to"] == "reset@x.by"
        assert "reset-password?token=" in fake.calls[0]["html_body"]
        assert "парол" in fake.calls[0]["subject"].lower()

    async def test_forgot_password_unknown_email_silently_202(
        self, api_client, monkeypatch
    ):
        fake = _FakeCeleryTask()
        monkeypatch.setattr(email_service, "send_email", fake)

        resp = await api_client.post(
            "/api/v1/auth/forgot-password", json={"email": "ghost@x.by"}
        )

        assert resp.status_code == 202
        assert fake.calls == []  # аккаунта нет — письмо не диспатчится
