"""Email-уведомления через SMTP (Celery) — durable-очередь (NOTIF-01).

Единственная точка отправки — задача ``app.tasks.email.send_email``:

* новый формат — ``send_email(outbox_id=...)``: письмо читается из строки
  ``email_outbox`` (PENDING → SENT/FAILED/SKIPPED). Строка фиксируется в БД
  ДО постановки задачи (services/email.py), поэтому потеря задачи/брокера
  не теряет письмо — beat-свипер ``requeue_stuck_emails`` реэнквитит
  зависшие PENDING;
* legacy-ветка — ``send_email(to=..., subject=..., html_body=...)``: сообщения
  старого формата, оставшиеся в брокере на момент деплоя, отправляются как
  раньше (без строки outbox). Ветку можно удалить после раскатки, когда в
  очереди гарантированно не осталось задач старого формата;
* SMTP не сконфигурирован (пустые SMTP_HOST/SMTP_FROM) → outbox-строка
  переводится в SKIPPED (терминальный, НЕ FAILED — это не ошибка письма, и
  НЕ PENDING — иначе свипер гонял бы его бесконечно) + warning в логах
  (НЕ молчаливый успех);
* сетевые ошибки SMTP → autoretry с экспоненциальным backoff (до 3 попыток);
  последняя неудача (``request.retries >= max_retries``) фиксирует FAILED на
  строке прямо в except-блоке — проще и надёжнее хука ``on_failure`` (тот
  требует отдельного sync-соединения к БД и не имеет доступа к сессии).

Идемпотентность: status=SENT проверяется перед отправкой — пере-доставка
(acks_late + reject_on_worker_lost) не шлёт письмо повторно. Окно «SMTP
принял, воркер умер до коммита SENT» даёт повторную отправку после
re-delivery — это осознанный at-least-once: дубль письма лучше потери.

См. ARCHITECTURE_PLAN.md §20 (Центр уведомлений), §5.2 (email_outbox).
"""
from __future__ import annotations

import asyncio
import html as html_lib
import re
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.system import EmailOutbox
from app.tasks._common import create_worker_db
from app.workers import celery_app

log = get_logger("app.tasks.email")

_SMTP_TIMEOUT_SEC = 15.0

# Отдельный движок для Celery-задач (NullPool — см. tasks/_common.py).
# Тесты подменяют ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine, _worker_session = create_worker_db()

# Простая конвертация HTML → текст (наши тела писем генерируются сами, не произвольные)
_BLOCK_TAG_RE = re.compile(r"</(?:p|div|li|h[1-6]|tr|br)\s*>|<br\s*/?>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def is_smtp_configured() -> bool:
    """SMTP считается настроенным, если заданы хост и адрес отправителя."""
    return bool(settings.smtp_host and settings.smtp_from)


def _html_to_text(html_body: str) -> str:
    """Простой текстовый body из HTML (без внешнего шаблона, см. докстринг модуля)."""
    text = _BLOCK_TAG_RE.sub("\n", html_body)
    text = _ANY_TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    lines = (ln.strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def _smtp_send(*, to: str, subject: str, html_body: str) -> None:
    """Реальная SMTP-отправка (общая для legacy- и outbox-веток)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(_html_to_text(html_body))
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT_SEC
    ) as smtp:
        if settings.smtp_tls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


@celery_app.task(
    bind=True,
    name="app.tasks.email.send_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_email(
    self,
    to: str | None = None,
    subject: str | None = None,
    html_body: str | None = None,
    outbox_id: str | None = None,
) -> dict:
    """Отправить письмо. Новый формат — ``outbox_id``; legacy — ``to/subject/html_body``.

    Возвращает статус, отражающий реальность: ``ok`` / ``skipped
    (no_transport|outbox_missing)`` / ``already_sent``; сетевые ошибки → autoretry.
    """
    if outbox_id is None:
        # --- legacy-ветка (сообщения старого формата в очереди на момент деплоя).
        # Удалить после раскатки, когда старых задач в брокере гарантированно нет.
        if to is None:
            raise ValueError("send_email: нужен outbox_id либо to/subject/html_body")
        if not is_smtp_configured():
            log.warning("email.skipped_no_transport", to=to, subject=subject)
            return {"status": "skipped", "reason": "no_transport", "to": to}
        _smtp_send(to=to, subject=subject, html_body=html_body or "")
        log.info("email.sent", to=to, subject=subject, attempt=self.request.retries + 1)
        return {"status": "ok", "to": to}
    return asyncio.run(_send_from_outbox(self, uuid.UUID(outbox_id)))


async def _send_from_outbox(self, outbox_id: uuid.UUID) -> dict:
    """Отправка письма из строки email_outbox (идемпотентно, с финализацией статуса)."""
    async with _worker_session() as db:
        row = await db.get(EmailOutbox, outbox_id)
        if row is None:
            # Строка удалена (например, чисткой очереди), а задача осталась:
            # отправлять нечего и не кому — не ошибка письма.
            log.warning("email.outbox_missing", outbox_id=str(outbox_id))
            return {"status": "skipped", "reason": "outbox_missing", "outbox_id": str(outbox_id)}
        if row.status in (EmailOutbox.STATUS_SENT, EmailOutbox.STATUS_SKIPPED):
            # Идемпотентность re-delivery (acks_late): терминальный статус — выходим.
            log.info(
                "email.already_finalized",
                outbox_id=str(outbox_id),
                status=row.status,
            )
            return {"status": "already_sent" if row.status == EmailOutbox.STATUS_SENT else "skipped",
                    "outbox_id": str(outbox_id)}

        if not is_smtp_configured():
            row.status = EmailOutbox.STATUS_SKIPPED
            await db.commit()
            log.warning(
                "email.skipped_no_transport", to=row.to, subject=row.subject
            )
            return {"status": "skipped", "reason": "no_transport", "to": row.to}

        # Попытка фиксируется ДО отправки: смерть воркера между SMTP и коммитом
        # не потеряет счётчик (строка останется PENDING — свипер повторит).
        row.attempts += 1
        await db.commit()
        try:
            _smtp_send(to=row.to, subject=row.subject, html_body=row.html_body)
        except Exception as exc:
            row.last_error = str(exc)
            if self.request.retries >= self.max_retries:
                # Ретраи исчерпаны (autoretry поднимет исключение в FAILURE):
                # фиксируем FAILED, чтобы свипер не реэнквитил безнадёжное письмо.
                row.status = EmailOutbox.STATUS_FAILED
            await db.commit()
            raise
        row.status = EmailOutbox.STATUS_SENT
        await db.commit()

    log.info(
        "email.sent",
        to=row.to,
        subject=row.subject,
        outbox_id=str(outbox_id),
        attempt=self.request.retries + 1,
    )
    return {"status": "ok", "to": row.to, "outbox_id": str(outbox_id)}


# ----------------------------- beat-свипер -----------------------------

# Строка PENDING старше этого срока = задача потеряна (брокер упал после
# коммита строки, воркер умер до задачи). Ретраи задачи живут максимум
# ~10 мин (backoff до 600 с), поэтому 10 минут — безопасный порог: живая
# задача успевает доработать до свипа.
STUCK_EMAIL_MINUTES = 10


@celery_app.task(
    bind=True,
    name="app.tasks.email.requeue_stuck_emails",
    autoretry_for=(),
)
def requeue_stuck_emails(self) -> dict:
    """Beat каждые 5 мин: зависшие PENDING-письма → повторная постановка в очередь.

    Идемпотентен: статус остаётся PENDING до успешной отправки, а проверка
    status=SENT в send_email делает дубли-постановки безвредными.
    """
    try:
        return asyncio.run(_requeue_stuck())
    except Exception as exc:  # непредвиденное — без слепого ретрая (beat повторит сам)
        log.exception("email.requeue.crashed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def _requeue_stuck() -> dict:
    """Реэнквит PENDING-строк с updated_at старше STUCK_EMAIL_MINUTES."""
    cutoff = datetime.now(UTC) - timedelta(minutes=STUCK_EMAIL_MINUTES)
    requeued = 0
    async with _worker_session() as db:
        rows = (
            await db.scalars(
                select(EmailOutbox).where(
                    EmailOutbox.status == EmailOutbox.STATUS_PENDING,
                    EmailOutbox.updated_at < cutoff,
                )
            )
        ).all()
        for row in rows:
            # «Аренда» через updated_at=now: без неё свипер каждые 5 минут
            # ставил бы дубли-задачи по одной и той же строке; with неё
            # повтор возможен не раньше, чем через STUCK_EMAIL_MINUTES.
            row.updated_at = datetime.now(UTC)
            await db.commit()
            try:
                send_email.delay(outbox_id=str(row.id))
                requeued += 1
            except Exception as exc:
                # Брокер недоступен: строка осталась PENDING (аренда истечёт
                # через 10 мин) — следующий свип повторит постановку.
                log.warning(
                    "email.requeue_enqueue_failed",
                    outbox_id=str(row.id),
                    error=str(exc),
                )
    if requeued:
        log.warning("email.requeued_stuck", count=requeued)
    return {"status": "ok", "requeued": requeued}
