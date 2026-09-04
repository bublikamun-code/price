"""Дашборд менеджера (фича G, §6 + §16 п.20-1).

Оркестрация запросов репозитория + Redis-кэш на 60 с. Кэш fail-open:
недоступный Redis никогда не ломает эндпоинт — данные считаются напрямую
(safe_get/safe_set молча деградируют в «мимо кэша», §4).
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import dashboard as client_repo
from app.repositories import manager_catalog as repo
from app.schemas.dashboard import ClientNewArrival, ClientPromo
from app.schemas.manager_catalog import (
    DashboardKPI,
    DashboardOut,
    OrdersByDayItem,
    RecentOrderItem,
    TopClientItem,
    TopProductItem,
)
from app.services.cache import cache

CACHE_KEY = "manager:dashboard:v1"
CACHE_TTL_SECONDS = 60
DAYS_WINDOW = 30
NEW_ARRIVALS_LIMIT = 5   # как в ClientDashboardService (§16 п.20-1)
PROMOS_LIMIT = 10

_MSK = ZoneInfo("Europe/Minsk")


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> DashboardOut:
        cached = await cache.safe_get(CACHE_KEY)
        if cached is not None:
            return DashboardOut.model_validate(cached)
        out = await self._build()
        await cache.safe_set(CACHE_KEY, out.model_dump(mode="json"), ttl=CACHE_TTL_SECONDS, tags=[])
        return out

    async def _build(self) -> DashboardOut:
        now_minsk = datetime.now(_MSK)
        today: date = now_minsk.date()
        week_start = today - timedelta(days=6)                 # 7 календарных дней вкл. сегодня
        month_start = today.replace(day=1)                     # текущий календарный месяц
        window_start = today - timedelta(days=DAYS_WINDOW - 1)
        new_client_threshold = (now_minsk - timedelta(days=7)).astimezone(timezone.utc)

        orders_today, orders_7d = await repo.fetch_orders_counts(
            self.db, today=today, week_start=week_start
        )
        revenue_month = await repo.fetch_revenue_month(self.db, month_start=month_start)
        new_clients = await repo.fetch_new_clients_count(
            self.db, threshold=new_client_threshold
        )
        active_imports = await repo.fetch_active_imports_count(self.db)
        by_day = await repo.fetch_orders_by_day(self.db, start_day=window_start)
        top_products = await repo.fetch_top_products(self.db, month_start=month_start)
        top_clients = await repo.fetch_top_clients(self.db, month_start=month_start)
        recent_orders = await repo.fetch_recent_orders(self.db)
        new_arrivals = await self._new_arrivals()
        promos = await self._promos()

        # Ровно DAYS_WINDOW календарных дней включая сегодня, по возрастанию,
        # без дней — нули (zero-fill).
        days = [today - timedelta(days=back) for back in range(DAYS_WINDOW - 1, -1, -1)]

        return DashboardOut(
            kpi=DashboardKPI(
                orders_today=orders_today,
                orders_7d=orders_7d,
                revenue_month=revenue_month,
                new_clients_7d=new_clients,
                active_imports=active_imports,
            ),
            orders_by_day=[OrdersByDayItem(date=d, count=by_day.get(d, 0)) for d in days],
            top_products=[
                TopProductItem(
                    product_id=row.product_id,
                    sku=row.sku,
                    name=row.name,
                    qty=int(row.qty),
                    revenue=Decimal(str(row.revenue)),
                )
                for row in top_products
            ],
            top_clients=[
                TopClientItem(
                    client_id=row.client_id,
                    name=row.name,
                    orders=int(row.orders),
                    revenue=Decimal(str(row.revenue)),
                )
                for row in top_clients
            ],
            recent_orders=[
                RecentOrderItem(
                    id=row.id,
                    created_at=row.created_at,
                    client_name=row.client_name,
                    status=row.status.value if hasattr(row.status, "value") else row.status,
                    total_amount=Decimal(str(row.total_amount)),
                )
                for row in recent_orders
            ],
            new_arrivals=new_arrivals,
            promos=promos,
        )

    async def _new_arrivals(self) -> list[ClientNewArrival]:
        """Последние поступления каталога (те же запросы, что клиентский дашборд)."""
        rows = await client_repo.fetch_new_arrivals(self.db, limit=NEW_ARRIVALS_LIMIT)
        return [self._carousel_item(product, photo_key) for product, photo_key in rows]

    async def _promos(self) -> list[ClientPromo]:
        """Товары со скидкой по договору (override_price) для блока «Акции»."""
        rows = await client_repo.fetch_promos(self.db, limit=PROMOS_LIMIT)
        return [
            ClientPromo(**self._carousel_item(product, photo_key).model_dump())
            for product, photo_key in rows
        ]

    @staticmethod
    def _carousel_item(product, photo_key) -> ClientNewArrival:
        # У менеджера нет персональной цены: в client_price кладём розничную
        # (base_price, BYN); has_discount — товар со скидкой по договору.
        return ClientNewArrival(
            id=product.id,
            sku=product.sku,
            name=product.name,
            photo_key=photo_key,
            client_price=Decimal(str(product.base_price)),
            currency="BYN",
            has_discount=product.override_price is not None,
        )
