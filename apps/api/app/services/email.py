"""Email service: рендер писем + постановка в durable-очередь (NOTIF-01).

Аудит 2026-09-06: ``queue_email`` был no-op — письма (включая ссылку
восстановления пароля) никогда не отправлялись. Теперь он пишет PENDING-строку
в ``email_outbox`` (своя сессия, немедленный коммит — строка переживает любой
сбой HTTP-запроса и брокера) и диспатчит Celery-задачу ``app.tasks.email.send_email``.

Отказоустойчивость (fire-and-forget, HTTP-запрос не роняется):
  * БД недоступна / таблицы нет (код раскатан раньше миграции 0026) → fallback
    к прямой постановке в брокер (старое поведение) + warning;
  * брокер упал ПОСЛЕ фиксации строки → строка остаётся PENDING, beat-свипер
    ``requeue_stuck_emails`` реэнквитит её позже — письмо не теряется;
  * ``dedupe_key`` → INSERT .. ON CONFLICT DO NOTHING: повторный вызов с тем же
    ключом не создаёт дубль и не ставит вторую задачу.

Шаблоны: каталог ``app/templates/notifications/`` не содержит шаблона письма
восстановления, поэтому тело строится здесь простым HTML (текстовую версию
из HTML генерирует задача).
"""

import html
import uuid

from sqlalchemy.dialects.postgresql import insert as postgres_insert

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.system import EmailOutbox
from app.services.pricing import quantize_money
from app.tasks.email import send_email

log = get_logger("app.services.email")

# Фабрика сессий — отдельный атрибут модуля (а не прямое использование
# AsyncSessionLocal): тесты подменяют его на тестовый session_factory, чтобы
# outbox-строки писались в тестовую БД, а не в settings.database_url.
_session_factory = AsyncSessionLocal


ORDER_STATUS_RU = {
    # Ключи = значения OrderStatus (app/models/enums.py, §9).
    "NEW": "Новая",
    "IN_PROGRESS": "В работе",
    "SHIPPED": "Отгружена",
    "COMPLETED": "Выполнена",
    "CANCELLED": "Отменена",
}

# Способ получения (orders.delivery_method, §9) — подпись в письмах и выгрузках.
DELIVERY_METHOD_RU = {
    "pickup": "Самовывоз",
    "delivery": "Доставка",
}


def format_order_no(seq: int) -> str:
    """Форматировать номер заказа."""
    return f"#{seq:06d}"


def build_password_reset_email(link: str) -> tuple[str, str]:
    """Вернуть (subject, html_body) письма сброса пароля.

    ``link`` — абсолютная или относительная ссылка на веб-страницу
    ``/reset-password?token=...`` (токен одноразовый, TTL 30 мин).
    """
    subject = "Сброс пароля — клиентский портал"
    html_body = (
        "<p>Здравствуйте!</p>"
        "<p>Вы запросили сброс пароля. Перейдите по ссылке, чтобы задать новый пароль "
        "(ссылка действует 30 минут):</p>"
        f'<p><a href="{link}">Сбросить пароль</a></p>'
        f'<p>Если кнопка не работает, скопируйте ссылку в браузер:<br>{link}</p>'
        "<p>Если вы не запрашивали сброс — просто проигнорируйте это письмо, "
        "пароль останется прежним.</p>"
    )
    return subject, html_body


# ----------------------------- заказы -----------------------------
# Палитра — токены витрины (apps/web/assets/css/main.css): тёплый фон,
# карточка, чернильный текст, терракотовое действие. Инлайн-CSS: часть
# почтовых клиентов вырезает <style>, атрибут style живёт везде; внешних
# ресурсов (картинки, шрифты) нет — письма должны читаться офлайн.

_INK = "#1b2a24"
_INK_MUTED = "#5c6660"
_SURFACE = "#fffdf8"
_CANVAS = "#f5f2eb"
_BORDER = "#c8d0c7"
_ACTION = "#c65c3b"

_LAYOUT_TPL = (
    '<div style="background:{canvas};padding:24px 12px;font-family:-apple-system,'
    'Segoe UI,Roboto,Arial,sans-serif;color:{ink};">'
    '<div style="max-width:560px;margin:0 auto;background:{surface};'
    'border:1px solid {border};border-radius:8px;padding:24px;">{body}</div>'
    '<p style="max-width:560px;margin:12px auto 0;font-size:12px;line-height:1.5;'
    'color:{muted};">Это автоматическое уведомление клиентского портала — '
    "отвечать на него не нужно.</p>"
    "</div>"
)


def _order_email_layout(body_html: str) -> str:
    """Базовый каркас письма: карточка на тёплом фоне + подпись-футер."""
    return _LAYOUT_TPL.format(
        canvas=_CANVAS,
        surface=_SURFACE,
        border=_BORDER,
        ink=_INK,
        muted=_INK_MUTED,
        body=body_html,
    )


def _cabinet_url(path: str) -> str:
    """Абсолютная ссылка на страницу кабинета.

    ``web_app_url`` пуст (dev) → относительный путь, как в ссылке сброса
    пароля (api/v1/auth.py): письмо остаётся осмысленным, просто без домена.
    """
    base = settings.web_app_url.rstrip("/") if settings.web_app_url else ""
    return f"{base}{path}"


def _field(label: str, value: str) -> str:
    """Строка «метка: значение» с инлайн-стилями (для сводки по заказу).

    Подставляемые значения экранируются (``html.escape``, §11): метки —
    серверные константы, а вот значение приходит из данных клиента (ФИО,
    компания, способ получения) и не должно уметь закрыть тег/атрибут.
    """
    return (
        f'<p style="margin:0 0 8px;font-size:14px;line-height:1.5;">'
        f'<span style="color:{_INK_MUTED};">{html.escape(label, quote=True)}:</span> '
        f"<strong>{html.escape(value, quote=True)}</strong></p>"
    )


def _button(url: str, label: str) -> str:
    """Кнопка-ссылка на кабинет (инлайн-стили, без картинок).

    ``url`` — свой, серверный (``_cabinet_url``), но экранируется для
    атрибута ``href`` с ``quote=True``: кавычка в URL иначе закрыла бы атрибут,
    а ``&amp;`` в query-строке — корректный HTML (рендерер декодирует сущности,
    поэтому ссылка остаётся валидной и копируется в исходном виде).
    Подпись ``label`` — текст, тоже экранируется.
    """
    safe_url = html.escape(url, quote=True)
    return (
        f'<p style="margin:20px 0 0;">'
        f'<a href="{safe_url}" style="display:inline-block;background:{_ACTION};'
        f'color:#fffdf8;text-decoration:none;font-size:14px;font-weight:600;'
        f'padding:10px 18px;border-radius:6px;">'
        f"{html.escape(label, quote=True)}</a></p>"
        f'<p style="margin:12px 0 0;font-size:13px;line-height:1.5;'
        f'color:{_INK_MUTED};">Если кнопка не работает, скопируйте ссылку '
        f"в браузер:<br>{safe_url}</p>"
    )


def _money(amount, currency_code: str) -> str:
    """Формат суммы как в выгрузках (tasks/export_order_pdf.py): 1234.56.

    Decimal + HALF_UP: ``round()``/``:%.2f`` по float округляли бы полу-копейки
    банкерским правилом и могли показать менеджеру сумму на копейку меньше
    фактической.
    """
    return f"{quantize_money(amount):.2f} {currency_code}"


def build_order_created_manager_email(
    order_no: str,
    client_name: str | None,
    client_company: str | None,
    total_amount,
    currency_code: str,
    delivery_method: str | None,
    items_count: int,
) -> tuple[str, str]:
    """Вернуть (subject, html_body) письма менеджеру о новой заявке.

    Содержимое повторяет сводку TG-уведомления (§20.1): номер, клиент,
    сумма, способ получения; ссылка — в список заявок кабинета менеджера.
    """
    subject = f"Новый заказ {order_no}"
    who = client_company or client_name
    if client_company and client_name:
        who = f"{client_company} ({client_name})"
    delivery = DELIVERY_METHOD_RU.get(delivery_method or "", delivery_method)
    rows = _field("Номер", order_no)
    if who:
        rows += _field("Клиент", who)
    rows += _field("Сумма", _money(total_amount, currency_code))
    if delivery:
        rows += _field("Способ получения", delivery)
    rows += _field("Позиций", str(items_count))
    body = (
        '<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">'
        f"Новый заказ {order_no}</h1>"
        "<p style=\"margin:0 0 16px;font-size:14px;line-height:1.5;\">"
        "Поступила новая заявка с портала:</p>"
        f'<div style="border-left:3px solid {_BORDER};padding-left:12px;">{rows}</div>'
        + _button(_cabinet_url("/manager/orders"), "Открыть заявки в кабинете")
    )
    return subject, _order_email_layout(body)


def build_order_status_changed_email(
    order_no: str,
    status_ru: str,
) -> tuple[str, str]:
    """Вернуть (subject, html_body) письма клиенту о смене статуса заявки."""
    subject = f"Заказ {order_no}: статус обновлён"
    body = (
        '<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">'
        f"Заказ {order_no}: статус обновлён</h1>"
        "<p style=\"margin:0 0 16px;font-size:14px;line-height:1.5;\">"
        "Здравствуйте! Статус вашей заявки изменился:</p>"
        f'<p style="margin:0 0 4px;font-size:14px;line-height:1.5;">'
        f'<span style="color:{_INK_MUTED};">Новый статус:</span> '
        f"<strong>{status_ru}</strong></p>"
        f'<p style="margin:0;font-size:13px;line-height:1.5;color:{_INK_MUTED};">'
        f"Заказ {order_no}</p>"
        + _button(_cabinet_url("/orders"), "Посмотреть заказ в кабинете")
    )
    return subject, _order_email_layout(body)


async def _enqueue_outbox(
    *, to: str, subject: str, html_body: str, dedupe_key: str | None
) -> uuid.UUID | None:
    """Вставить PENDING-строку в email_outbox. None — дедуп: ключ уже занят.

    Своя короткоживущая сессия + немедленный коммит: строка переживает любой
    сбой вызывающего HTTP-запроса и брокера. Конкурентная постановка с тем же
    dedupe_key: ON CONFLICT DO NOTHING даёт ровно одну строку; второй вызов
    получает None (дубль подавлен, новую задачу ставит только победитель).
    """
    outbox_id = uuid.uuid4()
    async with _session_factory() as db:
        stmt = (
            postgres_insert(EmailOutbox)
            .values(
                id=outbox_id,
                to=to,
                subject=subject,
                html_body=html_body,
                status=EmailOutbox.STATUS_PENDING,
                dedupe_key=dedupe_key,
            )
            # NULL dedupe_key не конфликтует (NULL != NULL в unique-индексе) —
            # письма без дедупликации вставляются свободно.
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        res = await db.execute(stmt)
        await db.commit()
        if not res.rowcount:
            return None
    return outbox_id


async def queue_email(
    to: str, subject: str, html_body: str, *, dedupe_key: str | None = None
) -> None:
    """Поставить письмо в durable-очередь (NOTIF-01): outbox-строка → Celery.

    Fire-and-forget: сбои БД/брокера не роняют HTTP-запрос — warning в лог.
    Дедупликация опциональна (``dedupe_key``): существующая строка → новую
    задачу не ставим вовсе.
    """
    try:
        outbox_id = await _enqueue_outbox(
            to=to, subject=subject, html_body=html_body, dedupe_key=dedupe_key
        )
    except Exception as exc:
        # БД недоступна (или код раскатан раньше миграции 0026): деградируем
        # к старому поведению «прямо в брокер» — письмо не теряем молча.
        log.warning(
            "email.outbox_write_failed", to=to, subject=subject, error=str(exc)
        )
        _dispatch_broker_legacy(to=to, subject=subject, html_body=html_body)
        return
    if outbox_id is None:
        log.info("email.duplicate_suppressed", to=to, dedupe_key=dedupe_key)
        return
    try:
        send_email.delay(outbox_id=str(outbox_id))
    except Exception as exc:
        # Брокер упал ПОСЛЕ фиксации строки: письмо не потеряно — строка
        # остаётся PENDING, свипер её реэнквитит (см. tasks/email.py).
        log.warning(
            "email.broker_enqueue_failed", outbox_id=str(outbox_id), error=str(exc)
        )


def _dispatch_broker_legacy(to: str, subject: str, html_body: str) -> None:
    """Прямая постановка в брокер старой сигнатурой (fallback при недоступной БД)."""
    try:
        send_email.delay(to=to, subject=subject, html_body=html_body)
    except Exception as exc:
        log.warning("email.enqueue_failed", to=to, subject=subject, error=str(exc))
