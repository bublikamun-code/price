"""Сервис заявок. См. ARCHITECTURE_PLAN.md §9, §17.2.

Ключевое — заморозка цен/курса при оформлении (§9): ``unit_price`` и
``exchange_rate`` фиксируются один раз и больше НЕ пересчитываются.
FSM переходов и инициаторов — см. таблицу в §9 (правка Этапа 6).

Сервис НЕ коммитит транзакцию — только ``flush``; коммит выполняет роутер
(см. существующий паттерн ``manager/prices.py``). 404/400/409-логика
поднимается как ``ValueError``; роутер превращает его в ``HTTPException``.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, StockStatus
from app.models.order import Order, OrderItem
from app.models.system import AuditLog
from app.repositories import catalog as catalog_repo, orders as orders_repo
from app.schemas.cart import CartRead
from app.schemas.order import OrderCreate
from app.services.cart import CartService
from app.services.pricing import PricingService

# Допустимые переходы статусов (см. §9 — таблица инициаторов).
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}
# Статусы, из которых клиент вправе отменить свою заявку.
CLIENT_CANCELABLE: set[OrderStatus] = {OrderStatus.NEW, OrderStatus.IN_PROGRESS}


class OrderService:
    """Жизненный цикл заявки: создание со снапшотом, списки, отмена, смена статуса."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingService(db)

    # -------------------------------------------------------------- create
    async def create(self, user, payload: OrderCreate) -> Order:
        """Оформление заявки: расчёт цен под клиента + снапшот + заморозка курса."""
        resolved = await self.pricing.resolve_rate(user, payload.price_calc_mode)
        currency_code = resolved.currency
        exchange_rate = float(resolved.rate) if resolved.rate is not None else 1.0

        # 1) Валидация позиций и расчёт позиций «на лету» (до INSERT).
        new_items: list[OrderItem] = []
        total = 0.0
        for ci in payload.items:
            product = await catalog_repo.get_by_sku(self.db, ci.sku)
            if product is None:
                raise ValueError(f"Товар {ci.sku} не найден")
            if product.stock_status == StockStatus.ARCHIVED:
                raise ValueError(f"Товар {ci.sku} архивный — недоступен для заказа")
            pr = await self.pricing.price_product(
                product, user, payload.price_calc_mode
            )
            unit_price = float(pr["client_price"])
            total += unit_price * ci.quantity
            snapshot = {
                "sku": product.sku,
                "name": product.name,
                "brand_id": str(product.brand_id) if product.brand_id else None,
            }
            new_items.append(
                OrderItem(
                    product_id=product.id,
                    product_snapshot=snapshot,
                    quantity=ci.quantity,
                    unit_price=unit_price,
                    currency_code=currency_code,
                    note=ci.note,
                )
            )

        # 2) INSERT order (flush — получаем id), затем items.
        order = Order(
            client_id=user.id,
            status=OrderStatus.NEW,
            currency_code=currency_code,
            exchange_rate=exchange_rate,
            rate_source=resolved.source,
            total_amount=round(total, 2),
            notes=payload.notes,
        )
        order = await orders_repo.create_order(self.db, order=order)
        for item in new_items:
            item.order_id = order.id
        await orders_repo.add_order_items(self.db, items=new_items)
        return order

    # --------------------------------------------------------------- lists
    async def list_for_client(
        self, user, status: OrderStatus | None, page: int, per_page: int
    ) -> tuple[list[Order], int]:
        limit, offset = per_page, (page - 1) * per_page
        rows = await orders_repo.fetch_orders(
            self.db, client_id=user.id, status=status, limit=limit, offset=offset
        )
        total = await orders_repo.count_orders(
            self.db, client_id=user.id, status=status
        )
        return rows, total

    async def list_for_manager(
        self,
        client_id: uuid.UUID | None,
        status: OrderStatus | None,
        manager_id: uuid.UUID | None,
        page: int,
        per_page: int,
    ) -> tuple[list[Order], int]:
        limit, offset = per_page, (page - 1) * per_page
        rows = await orders_repo.fetch_orders(
            self.db,
            client_id=client_id,
            manager_id=manager_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await orders_repo.count_orders(
            self.db, client_id=client_id, manager_id=manager_id, status=status
        )
        return rows, total

    # ---------------------------------------------------------------- get
    async def get(self, user, order_id: uuid.UUID, *, as_manager: bool) -> Order:
        order = await orders_repo.get_order(self.db, order_id=order_id)
        if order is None:
            raise ValueError("Заявка не найдена")
        # Клиент видит только свои заявки; несуществование не раскрываем.
        if not as_manager and order.client_id != user.id:
            raise ValueError("Заявка не найдена")
        return order

    # -------------------------------------------------------------- repeat
    async def repeat(self, user, order_id: uuid.UUID) -> CartRead:
        """Повтор заказа (фича C): позиции старой заявки → корзину с АКТУАЛЬНЫМИ ценами."""
        order = await self.get(user, order_id, as_manager=False)
        items = await orders_repo.get_order_items(self.db, order_id=order.id)
        cart_service = CartService(self.db)
        for item in items:
            sku = (item.product_snapshot or {}).get("sku")
            if not sku:
                continue
            try:
                await cart_service.add(user, sku, item.quantity, note=item.note)
            except ValueError:
                # Товар более недоступен (архив/удалён) — пропускаем тихо.
                continue
        return await cart_service.view(user)

    # -------------------------------------------------------------- cancel
    async def cancel(self, user, order_id: uuid.UUID) -> Order:
        order = await self.get(user, order_id, as_manager=False)
        if order.status not in CLIENT_CANCELABLE:
            raise ValueError("Заявку в этом статусе нельзя отменить")
        return await orders_repo.update_order_status(
            self.db, order=order, new_status=OrderStatus.CANCELLED
        )

    # -------------------------------------------------------- change_status
    async def change_status(
        self,
        manager,
        order_id: uuid.UUID,
        new_status: OrderStatus,
        manager_id: uuid.UUID | None = None,
    ) -> Order:
        order = await self.get(manager, order_id, as_manager=True)
        if new_status not in ALLOWED_TRANSITIONS[order.status]:
            raise ValueError(
                f"Запрещённый переход статуса: {order.status.value} → {new_status.value}"
            )
        before = {"status": order.status.value, "manager_id": str(order.manager_id) if order.manager_id else None}
        # Сначала аудит (перед изменением), затем смена статуса.
        self.db.add(
            AuditLog(
                actor_id=manager.id,
                action="order.status_change",
                target_type="order",
                target_id=order.id,
                before=before,
                after={
                    "status": new_status.value,
                    "manager_id": str(manager_id) if manager_id else (str(order.manager_id) if order.manager_id else None),
                },
            )
        )
        return await orders_repo.update_order_status(
            self.db, order=order, new_status=new_status, manager_id=manager_id
        )
