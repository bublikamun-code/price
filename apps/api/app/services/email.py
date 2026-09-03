"""Email service — заглушка (501 Not Implemented)."""


ORDER_STATUS_RU = {
    "DRAFT": "Черновик",
    "PENDING": "Ожидает",
    "CONFIRMED": "Подтверждён",
    "SHIPPED": "Отгружен",
    "DELIVERED": "Доставлен",
    "CANCELLED": "Отменён",
}


def format_order_no(seq: int) -> str:
    """Форматировать номер заказа — заглушка."""
    return f"#{seq:06d}"


def build_password_reset_email(link: str) -> tuple[str, str]:
    """Вернуть (subject, html_body) — заглушка."""
    return "Сброс пароля", f"<p>Заглушка: email service не реализован. Ссылка: {link}</p>"


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
    """Поставить письмо в очередь — заглушка (ничего не делает)."""
    pass
