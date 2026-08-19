"""Репозиторий курсов валют (§17). Коммитит вызывающий."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.pricing import ExchangeRate

# Курсы для отслеживания. BYN — базовая, её курс не нужен (как в задаче НБ РБ).
TRACKED = tuple(sorted(set(settings.display_currency_list) - {"BYN"}))


async def latest_rates(db: AsyncSession, *, days: int = 7) -> list[ExchangeRate]:
    """Курсы отслеживаемых валют за последние `days` дней (все источники)."""
    since = date.today() - timedelta(days=days - 1)
    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.currency_code.in_(TRACKED), ExchangeRate.fetched_at >= since)
        .order_by(ExchangeRate.currency_code.asc(), ExchangeRate.fetched_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def latest_nbrb(db: AsyncSession, currency_code: str) -> ExchangeRate | None:
    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.currency_code == currency_code, ExchangeRate.source == "NBRB")
        .order_by(ExchangeRate.fetched_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


async def upsert_manual(
    db: AsyncSession,
    *,
    currency_code: str,
    rate,
    fetched_at: date,
    scale: int = 1,
) -> ExchangeRate:
    """Вставка/обновление ручного курса (source=MANUAL) по uq_rates_currency_date_source."""
    stmt = pg_insert(ExchangeRate).values(
        currency_code=currency_code,
        rate=rate,
        scale=scale,
        fetched_at=fetched_at,
        source="MANUAL",
        is_manual=True,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_rates_currency_date_source",
        set_={"rate": stmt.excluded.rate, "scale": stmt.excluded.scale},
    )
    await db.execute(stmt)
    row = await db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.fetched_at == fetched_at,
            ExchangeRate.source == "MANUAL",
        )
    )
    assert row is not None
    return row
