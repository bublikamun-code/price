"""NotificationDispatcher-минимум: сборка текстов уведомлений (§20.1).

Тексты рендерятся из Jinja2-шаблонов ``app/templates/notifications/*.j2``.
Локализация — RU. Разделение «сборка текста» / «доставка» (in-app, Telegram)
соответствует чистой архитектуре: сервис не лезёт в БД и не шлёт в сеть.
"""
from __future__ import annotations

from app.core.templates import render_notification
from app.repositories.price_changes import DigestRecipient, VersionDiff

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
