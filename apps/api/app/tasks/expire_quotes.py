"""Истечение срока действия КП (Celery beat). Этап 8 роадмапа.

Beat-задача раз в час помечает EXPIRED-ом КП, чей ``valid_until`` прошёл:
``UPDATE quotes SET status='EXPIRED' WHERE status='SENT' AND valid_until < now()``.

Помимо beat-свипа сервис делает ЛЕНИВУЮ маркировку при чтении/accept
(``repositories/quotes.py::expire_due``) — клиент, открывший КП сразу после
истечения срока, получает 409 QUOTE_EXPIRED, не дожидаясь ближайшего свипа.
Beat гарантирует маркировку и для КП, которые никто не открывал.

Задача идемпотентна: повторный прогон не находит строк (WHERE status='SENT'),
слепой авто-ретрай (``autoretry_for=()``) не нужен — beat повторит сам.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, update

from app.core.logging import get_logger
from app.models.enums import QuoteStatus
from app.models.quote import Quote
from app.tasks._common import create_worker_db
from app.workers import celery_app

log = get_logger("app.tasks.expire_quotes")

# Отдельный движок для Celery-задач (NullPool — см. tasks/_common.py).
# Тесты подменяют ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine, _worker_session = create_worker_db()


@celery_app.task(
    bind=True,
    name="app.tasks.expire_quotes.expire_quotes",
    autoretry_for=(),
)
def expire_quotes(self) -> dict:
    """Beat (ежечасно, :05): истёкшие SENT-КП → EXPIRED.

    Идемпотентен: WHERE status='SENT' — повторный прогон не находит строк.
    """
    try:
        return asyncio.run(_expire_quotes())
    except Exception as exc:  # непредвиденное — без слепого ретрая (beat повторит сам)
        log.exception("quotes.expire.crashed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def _expire_quotes() -> dict:
    """UPDATE ... WHERE status='SENT' AND valid_until < now() → EXPIRED."""
    async with _worker_session() as db:
        result = await db.execute(
            update(Quote)
            .where(
                Quote.status == QuoteStatus.SENT,
                Quote.valid_until < func.now(),
            )
            .values(status=QuoteStatus.EXPIRED)
        )
        await db.commit()
        expired = int(result.rowcount or 0)
    if expired:
        log.info("quotes.expired", count=expired)
    return {"status": "ok", "expired": expired}


__all__ = ["expire_quotes"]
