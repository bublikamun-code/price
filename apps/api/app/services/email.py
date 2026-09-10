"""Email service: рендер писем + постановка в очередь через Celery.

Аудит 2026-09-06: ``queue_email`` был no-op — письма (включая ссылку
восстановления пароля) никогда не отправлялись. Теперь он диспатчит Celery-задачу
``app.tasks.email.send_email`` (реальная SMTP-отправка); ошибки брокера
не роняют вызывающий эндпоинт (fire-and-forget, warning в лог).

Шаблоны: каталог ``app/templates/notifications/`` не содержит шаблона письма
восстановления, поэтому тело строится здесь простым HTML (текстовую версию
из HTML генерирует задача).
"""

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


def build_order_created_manager_email(
    order_no: str,
    client_name: str | None,
    client_company: str | None,
    total_amount: float,
    currency_code: str,
    delivery_method: str | None,
    items_count: int,
) -> tuple[str, str]:
    """Вернуть (subject, html_body) — заглушка."""
    return "Новый заказ", f"<p>Заглушка: заказ {order_no}</p>"


def build_order_status_changed_email(
    order_no: str,
    status_ru: str,
) -> tuple[str, str]:
    """Вернуть (subject, html_body) — заглушка."""
    return f"Заказ {order_no}", f"<p>Заглушка: статус {status_ru}</p>"


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
