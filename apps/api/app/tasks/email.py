"""Email-уведомления через SMTP (Celery).

Аудит 2026-09-06: отправка была no-op — пользователи не получали письма
(в т.ч. ссылку восстановления пароля). Теперь единственная точка отправки —
задача ``app.tasks.email.send_email``:

* SMTP не сконфигурирован (пустые SMTP_HOST/SMTP_FROM) → ``skipped/no_transport``
  с явным warning в логах (НЕ молчаливый успех);
* сетевые ошибки SMTP → autoretry с экспоненциальным backoff (до 3 попыток);
* текстовая альтернатива формируется из HTML прямо в задаче: jinja-шаблона для
  письма восстановления в ``app/templates/notifications/`` нет (каталог содержит
  только price_changed_*/rate_fetch_failed).

См. ARCHITECTURE_PLAN.md §20 (Центр уведомлений).
"""
from __future__ import annotations

import html as html_lib
import re
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.workers import celery_app

log = get_logger("app.tasks.email")

_SMTP_TIMEOUT_SEC = 15.0

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


@celery_app.task(
    bind=True,
    name="app.tasks.email.send_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_email(self, to: str, subject: str, html_body: str) -> dict:
    """Отправить письмо через SMTP. Возвращает статус, отражающий реальность:
    ``ok`` / ``skipped (no_transport)``; сетевые ошибки → autoretry."""
    if not is_smtp_configured():
        log.warning("email.skipped_no_transport", to=to, subject=subject)
        return {"status": "skipped", "reason": "no_transport", "to": to}

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

    log.info(
        "email.sent", to=to, subject=subject, attempt=self.request.retries + 1
    )
    return {"status": "ok", "to": to}
