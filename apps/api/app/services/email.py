"""Email service: рендер писем + постановка в очередь через Celery.

Аудит 2026-09-06: ``queue_email`` был no-op — письма (включая ссылку
восстановления пароля) никогда не отправлялись. Теперь он диспатчит Celery-задачу
``app.tasks.email.send_email`` (реальная SMTP-отправка); ошибки брокера
не роняют вызывающий эндпоинт (fire-and-forget, warning в лог).

Шаблоны: каталог ``app/templates/notifications/`` не содержит шаблона письма
восстановления, поэтому тело строится здесь простым HTML (текстовую версию
из HTML генерирует задача).
"""

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks.email import send_email

log = get_logger("app.services.email")


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
    """Строка «метка: значение» с инлайн-стилями (для сводки по заказу)."""
    return (
        f'<p style="margin:0 0 8px;font-size:14px;line-height:1.5;">'
        f'<span style="color:{_INK_MUTED};">{label}:</span> '
        f"<strong>{value}</strong></p>"
    )


def _button(url: str, label: str) -> str:
    """Кнопка-ссылка на кабинет (инлайн-стили, без картинок)."""
    return (
        f'<p style="margin:20px 0 0;">'
        f'<a href="{url}" style="display:inline-block;background:{_ACTION};'
        f'color:#fffdf8;text-decoration:none;font-size:14px;font-weight:600;'
        f'padding:10px 18px;border-radius:6px;">{label}</a></p>'
        f'<p style="margin:12px 0 0;font-size:13px;line-height:1.5;'
        f'color:{_INK_MUTED};">Если кнопка не работает, скопируйте ссылку '
        f'в браузер:<br>{url}</p>'
    )


def _money(amount: float, currency_code: str) -> str:
    """Формат суммы как в выгрузках (tasks/export_order_pdf.py): 1234.56."""
    return f"{float(amount):.2f} {currency_code}"


def build_order_created_manager_email(
    order_no: str,
    client_name: str | None,
    client_company: str | None,
    total_amount: float,
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


def queue_email(to: str, subject: str, html_body: str) -> None:
    """Поставить письмо в очередь (Celery ``send_email``).

    Fire-and-forget: сбой брокера не роняет HTTP-запрос — пишем warning.
    """
    try:
        send_email.delay(to=to, subject=subject, html_body=html_body)
    except Exception as exc:
        log.warning(
            "email.enqueue_failed", to=to, subject=subject, error=str(exc)
        )
