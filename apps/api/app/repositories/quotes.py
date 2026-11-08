"""Репозиторий коммерческих предложений. Этап 8 роадмапа.

Только запросы к БД; правила (жизненный цикл, заморозка сумм при SEND,
доменные ошибки) — в ``services/quote.py``. Как и соседние репозитории —
только ``flush``, коммитит роутер (§4).
"""
import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import QuoteStatus
from app.models.quote import Quote, QuoteItem

# PG-последовательность сквозных номеров КП (создаётся миграцией 0029;
# ORM-декларация — app.models.quote.quotes_seq_numbering).
QUOTES_SEQ_NAME = "quotes_seq_seq"


async def next_quote_seq(db: AsyncSession) -> int:
    """Следующий сквозной номер КП: nextval('quotes_seq_seq').

    Ровно тот же приём, что у ``next_invoice_seq``/``next_order_seq``: nextval
    атомарен, MAX(seq)+1 падал бы по ``uq_quotes_seq`` при конкурентном SEND
    (§16 п.9).
    """
    return int(await db.scalar(text(f"SELECT nextval('{QUOTES_SEQ_NAME}')")))


async def get_quote(db: AsyncSession, *, quote_id: uuid.UUID) -> Quote | None:
    """КП с позициями (selectinload — проекция деталей читает quote.items)."""
    stmt = (
        select(Quote)
        .options(selectinload(Quote.items))
        .where(Quote.id == quote_id)
    )
    return await db.scalar(stmt)


async def fetch_quotes(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    status: QuoteStatus | None = None,
    limit: int,
    after: dict[str, str] | None = None,
    include_draft: bool = True,
) -> list[Quote]:
    """Keyset-страница КП: сортировка created_at DESC, id DESC (tie-break).

    ``organization_id=None`` — менеджерский список (все организации);
    клиентский вызов проходит через сервис с обязательным org-фильтром
    (org-scope, этап 8). ``include_draft=False`` — клиентская лента: черновики
    менеджера клиенту не видны. ``after`` — декодированный курсор
    (см. api/v2/pagination.py).
    """
    stmt = select(Quote)
    if organization_id is not None:
        stmt = stmt.where(Quote.organization_id == organization_id)
    if status is not None:
        stmt = stmt.where(Quote.status == status)
    if not include_draft:
        stmt = stmt.where(Quote.status != QuoteStatus.DRAFT)
    if after is not None:
        after_created_at = datetime.fromisoformat(after["value"])
        after_id = uuid.UUID(after["id"])
        stmt = stmt.where(
            or_(
                Quote.created_at < after_created_at,
                and_(Quote.created_at == after_created_at, Quote.id < after_id),
            )
        )
    stmt = stmt.order_by(Quote.created_at.desc(), Quote.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_quote(
    db: AsyncSession, *, quote: Quote, items: list[QuoteItem]
) -> Quote:
    """Создать КП с позициями (flush — получаем id, коммитит роутер).

    Позиции присваиваются через ``quote.items`` ДО flush: коллекция остаётся
    загруженной в сессии, и проекция ``quote_out(quote)`` сразу после создания
    не провоцирует ленивую загрузку (MissingGreenlet в async-сессии).
    """
    quote.items = items
    db.add(quote)
    await db.flush()
    return quote


async def replace_items(
    db: AsyncSession, *, quote: Quote, items: list[QuoteItem]
) -> None:
    """Полная замена позиций (PATCH DRAFT): коллекция с delete-orphan —
    присваивание нового списка помечает старые строки на удаление, новые
    получает FK через каскад flush."""
    quote.items = items
    await db.flush()


async def set_status(
    db: AsyncSession, *, quote: Quote, status: QuoteStatus
) -> Quote:
    quote.status = status
    await db.flush()
    return quote


async def expire_due(db: AsyncSession) -> int:
    """Ленивая маркировка истёкших КП (этап 8): SENT + valid_until < now() →
    EXPIRED. Дублирует beat-задачу ``expire_quotes``: клиент, открывший КП
    после истечения срока, видит EXPIRED сразу, а не до ближайшего свипа.
    Возвращает число помеченных строк."""
    result = await db.execute(
        update(Quote)
        .where(Quote.status == QuoteStatus.SENT, Quote.valid_until < func.now())
        .values(status=QuoteStatus.EXPIRED)
    )
    return result.rowcount or 0


__all__ = [
    "QUOTES_SEQ_NAME",
    "create_quote",
    "expire_due",
    "fetch_quotes",
    "get_quote",
    "next_quote_seq",
    "replace_items",
    "set_status",
]
