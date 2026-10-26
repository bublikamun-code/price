"""NotificationDispatcher-минимум: сборка текстов уведомлений (§20.1).

Тексты рендерятся из Jinja2-шаблонов ``app/templates/notifications/*.j2``.
Локализация — RU. Разделение «сборка текста» / «доставка» (in-app, Telegram)
соответствует чистой архитектуре: сервис не лезёт в БД и не шлёт в сеть.
"""
from __future__ import annotations

from app.core.templates import render_notification
from app.services.pricing import quantize_money
from app.services.price_changes import DigestRecipient, VersionDiff

# Подписи категорий для клиентского дайджеста (§20.3).
_CATEGORY_LABELS = {
    "up": "подорожание",
    "down": "удешевление",
    "new": "новинка",
    "override_reset": "сброшена фикс-цена",
}


def build_rate_fetch_failed_text(last_date: str | None) -> str:
    """Текст алёрта о недоступности курса НБ РБ (§20.3 RATE_FETCH_FAILED)."""
    return render_notification("rate_fetch_failed.j2", last_date=last_date)


def build_order_status_changed_text(order_number: str, status_ru: str) -> str:
    """Текст клиенту о смене статуса заявки (§20.3 ORDER_STATUS_CHANGED).

    ``order_number`` уже отформатирован (``format_order_no`` → «#000123»):
    сервис текстов не знает, откуда пришёл номер.
    """
    return render_notification(
        "order_status_changed.j2", order_number=order_number, status_ru=status_ru
    )


def build_invoice_issued_text(invoice_number: str, amount, currency_code: str) -> str:
    """Текст клиенту о выставленном счёте (§20.3 INVOICE_ISSUED).

    ``amount`` — Decimal из invoices.total_amount; формат как в письмах/выгрузках
    (quantize_money HALF_UP — иначе float-округление теряло бы копейку).
    """
    return render_notification(
        "invoice_issued.j2",
        invoice_number=invoice_number,
        amount=f"{quantize_money(amount):.2f}",
        currency=currency_code,
    )


def build_import_done_text(filename: str, rows_ok: int, rows_error: int, rows_total: int) -> str:
    """Сводка менеджерам об успешном импорте (§20.3 IMPORT_DONE)."""
    return render_notification(
        "import_done.j2",
        filename=filename,
        rows_ok=rows_ok,
        rows_error=rows_error,
        rows_total=rows_total,
    )


def build_import_failed_text(filename: str | None, reason: str) -> str:
    """Алёрт менеджерам о провале импорта (§20.3 IMPORT_FAILED)."""
    return render_notification("import_failed.j2", filename=filename, reason=reason)


def build_manager_price_changed_text(diff: VersionDiff) -> str:
    """Сводный текст для менеджера (§20.3 PRICE_CHANGED)."""
    return render_notification("price_changed_manager.j2", diff=diff)


def build_client_digest_text(recipient: DigestRecipient) -> str:
    """Текст дайджеста для клиента (§20.3 PRICE_CHANGED_DIGEST).

    Выводит первые 10 позиций, остаток схлопывает в «…и ещё N».
    """
    items = [
        {
            "sku": a.sku,
            "name": a.name,
            "sign": "+" if a.category == "up" else "−",
            "delta_percent": a.delta_percent if a.delta_percent is not None else "—",
            "category": _CATEGORY_LABELS[a.category],
        }
        for a in recipient.affected[:10]
    ]
    return render_notification(
        "price_changed_digest_client.j2",
        count=len(recipient.affected),
        items=items,
    )
