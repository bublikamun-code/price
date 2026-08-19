"""Сервис курсов валют для менеджер-панели (§6, §17, §16 п.19)."""
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import ExchangeRate
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import rates as rates_repo
from app.schemas.currency import ManualRateIn


def refresh_nbrb() -> None:
    """Постановка Celery-задачи загрузки курсов НБ РБ (lazy-import без циклов)."""
    from app.tasks.fetch_nbrb_rates import fetch_rates

    fetch_rates.delay()


class CurrencyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_rates(self) -> list[ExchangeRate]:
        return await rates_repo.latest_rates(self.db, days=7)

    async def set_manual_rate(self, manager: User, payload: ManualRateIn) -> ExchangeRate:
        rate = await rates_repo.upsert_manual(
            self.db,
            currency_code=payload.currency_code,
            rate=payload.rate,
            fetched_at=payload.fetched_at or date.today(),
        )
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="currency.rate.manual",
            target_type="exchange_rate",
            target_id=rate.id,
            after={
                "currency_code": rate.currency_code,
                "rate": str(rate.rate),
                "fetched_at": rate.fetched_at.isoformat(),
                "source": rate.source,
            },
        )
        await self.db.commit()
        await self.db.refresh(rate)
        return rate
