"""Клиентский дашборд «Моя аналитика» (§6 + §16 п.20, экран /dashboard).

Оркестрация запросов репозитория + Redis-кэш на 60 с (как менеджерский
дашборд, services/dashboard.py): недоступный Redis никогда не ломает
эндпоинт — данные считаются напрямую (safe_get/safe_set, §4). Инвалидация
не критична: данные персональные и ключ протухает по TTL.

Все агрегаты — в скоупе user_id текущего пользователя. Дневные бакеты и
границы периодов — по календарю Europe/Minsk.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import dashboard as repo
from app.schemas.dashboard import (
    ClientActiveOrder,
    ClientDashboardKPI,
    ClientDashboardOut,
    ClientNewArrival,
    ClientOrdersByDayItem,
    ClientPriceChange,
    ClientQuickActions,
    ClientRecentOrder,
    ClientStatusCount,
    ClientTopProduct,
)
from app.services.cache import cache
from app.services.pricing import (
    PricingService,
    client_price_byn,
    convert_to_currency,
)

CACHE_KEY_PREFIX = "client:dashboard:v1"
CACHE_TTL_SECONDS = 60
DAYS_WINDOW = 30
TOP_PRODUCTS_LIMIT = 5
RECENT_ORDERS_LIMIT = 5
FAVORITES_LIMIT = 10
NEW_ARRIVALS_LIMIT = 5

_TWO_PLACES = Decimal("0.01")
_MSK = ZoneInfo("Europe/Minsk")


def _order_number(order_id: uuid.UUID, seq: int | None) -> str:
    """Отображаемый номер заявки (как formatOrderNumber на фронте)."""
    if seq is not None:
        return f"З-{seq:06d}"
    return f"№{str(order_id)[:8]}"


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


class ClientDashboardService:
    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.pricing = PricingService(db)

    async def get(self) -> ClientDashboardOut:
        key = f"{CACHE_KEY_PREFIX}:{self.user.id}"
        cached = await cache.safe_get(key)
        if cached is not None:
            return ClientDashboardOut.model_validate(cached)
        out = await self._build()
        await cache.safe_set(key, out.model_dump(mode="json"), ttl=CACHE_TTL_SECONDS, tags=[])
        return out

    async def _build(self) -> ClientDashboardOut:
        now_minsk = datetime.now(_MSK)
        today: date = now_minsk.date()
        month_start = today.replace(day=1)                     # текущий календарный месяц
        window_start = today - timedelta(days=DAYS_WINDOW - 1)

        client_id = self.user.id
        orders_total, orders_month, total_spent = await repo.fetch_client_kpi(
            self.db, client_id=client_id, month_start=month_start
        )
        avg_order = (
            (total_spent / orders_total).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            if orders_total
            else Decimal("0.00")
        )
        by_day = await repo.fetch_orders_by_day(self.db, client_id=client_id, start_day=window_start)
        status_counts = await repo.fetch_status_counts(self.db, client_id=client_id)
        top_products = await repo.fetch_top_products(
            self.db, client_id=client_id, limit=TOP_PRODUCTS_LIMIT
        )
        recent_orders = await repo.fetch_recent_orders(
            self.db, client_id=client_id, limit=RECENT_ORDERS_LIMIT
        )
        active_orders = await repo.fetch_active_orders(self.db, client_id=client_id)
        last_order_id = await repo.fetch_last_order_id(self.db, client_id=client_id)
        price_changes = await self._favorite_price_changes()
        new_arrivals = await self._new_arrivals()

        # Ровно DAYS_WINDOW календарных дней включая сегодня, по возрастанию,
        # без дней — нули (zero-fill).
        days = [today - timedelta(days=back) for back in range(DAYS_WINDOW - 1, -1, -1)]

        return ClientDashboardOut(
            kpi=ClientDashboardKPI(
                orders_total=orders_total,
                orders_this_month=orders_month,
                total_spent_byn=total_spent,
                avg_order_byn=avg_order,
            ),
            orders_by_day=[ClientOrdersByDayItem(date=d, count=by_day.get(d, 0)) for d in days],
            status_counts=[
                ClientStatusCount(status=_status_value(row.status), count=int(row.cnt))
                for row in status_counts
            ],
            top_products=[
                ClientTopProduct(
                    product_id=row.product_id,
                    sku=row.sku,
                    name=row.name,
                    qty=int(row.qty),
                    revenue_byn=Decimal(str(row.revenue)),
                )
                for row in top_products
            ],
            recent_orders=[
                ClientRecentOrder(
                    id=row.id,
                    created_at=row.created_at,
                    status=_status_value(row.status),
                    total_amount=Decimal(str(row.total_amount)),
                    seq=row.seq,
                )
                for row in recent_orders
            ],
            active_orders=[
                ClientActiveOrder(
                    id=row.id,
                    number=_order_number(row.id, row.seq),
                    created_at=row.created_at,
                    status=_status_value(row.status),
                    total_amount=Decimal(str(row.total_amount)),
                )
                for row in active_orders
            ],
            favorite_price_changes=price_changes,
            new_arrivals=new_arrivals,
            quick_actions=ClientQuickActions(repeat_order_id=last_order_id),
        )

    async def _favorite_price_changes(self) -> list[ClientPriceChange]:
        """Товары из избранного, где клиентская цена изменилась между
        последними двумя версиями прайса (price_history, фича J).

        Старая цена — предпоследняя запись истории; текущая — из products.
        Одна запись истории — товар впервые появился в прайсе (категория
        «new»); цена не изменилась или истории нет — товар пропускается.
        Скидка клиента применяется к обеим ценам (§8); валюта — display-курс.
        """
        resolved = await self.pricing.resolve_rate(self.user, "fixed")
        rows = await repo.fetch_favorite_products(
            self.db, user_id=self.user.id, limit=FAVORITES_LIMIT
        )
        out: list[ClientPriceChange] = []
        for product, photo_key in rows:
            history = await repo.fetch_last_price_history(
                self.db, product_id=product.id, limit=2
            )
            if not history:
                continue  # истории импортов нет — изменение цены не отследить
            discount = await self.pricing.get_discount_for_brand(
                self.user.id, product.brand_id
            )
            new_byn = client_price_byn(product.base_price, product.override_price, discount)
            new_price = convert_to_currency(new_byn, resolved.rate, resolved.scale)
            if len(history) == 1:
                out.append(
                    ClientPriceChange(
                        product_id=product.id,
                        sku=product.sku,
                        name=product.name,
                        photo_key=photo_key,
                        new_client_price=new_price,
                        old_client_price=None,
                        currency=resolved.currency,
                        category="new",
                        delta_percent=None,
                    )
                )
                continue
            prev = history[1]
            old_byn = client_price_byn(prev.base_price, prev.override_price, discount)
            if old_byn == new_byn or old_byn == 0:
                continue  # цена не изменилась; от нулевой старой % не считаем
            old_price = convert_to_currency(old_byn, resolved.rate, resolved.scale)
            delta = ((new_byn - old_byn) / old_byn * Decimal(100)).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
            out.append(
                ClientPriceChange(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    photo_key=photo_key,
                    new_client_price=new_price,
                    old_client_price=old_price,
                    currency=resolved.currency,
                    category="down" if new_byn < old_byn else "up",
                    delta_percent=str(delta),
                )
            )
        return out

    async def _new_arrivals(self) -> list[ClientNewArrival]:
        """Последние поступления каталога с клиентской ценой (§8, §17)."""
        rows = await repo.fetch_new_arrivals(self.db, limit=NEW_ARRIVALS_LIMIT)
        out: list[ClientNewArrival] = []
        for product, photo_key in rows:
            pr = await self.pricing.price_product(product, self.user, "fixed")
            out.append(
                ClientNewArrival(
                    id=product.id,
                    sku=product.sku,
                    name=product.name,
                    photo_key=photo_key,
                    client_price=Decimal(str(pr["client_price"])),
                    currency=pr["currency"],
                    has_discount=pr["has_discount"],
                )
            )
        return out
