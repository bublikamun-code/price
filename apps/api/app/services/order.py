"""Сервис заявок. См. ARCHITECTURE_PLAN.md §9, §17.2.

Ключевое — заморозка цен/курса при оформлении (§9): ``unit_price`` и
``exchange_rate`` фиксируются один раз и больше НЕ пересчитываются.
FSM переходов и инициаторов — см. таблицу в §9 (правка Этапа 6).

Сервис НЕ коммитит транзакцию — только ``flush``; коммит выполняет роутер
(см. существующий паттерн ``manager/prices.py``). Доменные ошибки содержат
стабильный машинный код и преобразуются роутером в HTTP-ответ.
"""
import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, StockStatus
from app.models.order import Order, OrderIdempotency, OrderItem
from app.models.system import AuditLog
from app.repositories import cart as cart_repo
from app.repositories import catalog as catalog_repo
from app.repositories import orders as orders_repo
from app.schemas.cart import CartRead
from app.schemas.order import OrderCreate, OrderItemCreate
from app.schemas.v2.cart import CartSummary
from app.schemas.v2.common import MAX_DATABASE_INTEGER
from app.schemas.v2.orders import OrderCreate as OrderCreateV2
from app.services.cart import CartService
from app.services.cart_v2 import CartQuantityOverflowError, CartV2Service
from app.services.organizations import OrganizationContextService
from app.repositories import organizations as organizations_repo
from app.services.pricing import PricingService

# Допустимые переходы статусов (см. §9 — таблица инициаторов).
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


class OrderError(Exception):
    """Доменная ошибка заявки с машинным кодом для API v2."""

    code = "ORDER_ERROR"
    status_code = 400
    title = "Ошибка заявки"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class OrderNotFoundError(OrderError):
    code = "ORDER_NOT_FOUND"
    status_code = 404
    title = "Заявка не найдена"


class OrderAddressNotFoundError(OrderError):
    """DELIVERY с address_id, которого нет в организации клиента (Этап 2)."""

    code = "ADDRESS_NOT_FOUND"
    status_code = 404
    title = "Адрес не найден"


class ProductNotFoundError(OrderError):
    code = "PRODUCT_NOT_FOUND"
    status_code = 404
    title = "Товар не найден"


class ProductUnavailableError(OrderError):
    code = "PRODUCT_UNAVAILABLE"
    status_code = 400
    title = "Товар недоступен"


class StockExceededError(OrderError):
    """Позиции заказано больше, чем доступно (product.stock_qty IS NOT NULL)."""

    code = "INSUFFICIENT_STOCK"
    status_code = 409
    title = "Недостаточно товара"

    def __init__(self, sku: str, available: int) -> None:
        self.sku = sku
        self.available = available
        super().__init__(f"По позиции {sku} доступно только {available} шт")


class OrderNotCancelableError(OrderError):
    code = "ORDER_NOT_CANCELABLE"
    status_code = 409
    title = "Заявку нельзя отменить"


class InvalidOrderTransitionError(OrderError):
    code = "INVALID_ORDER_TRANSITION"
    status_code = 409
    title = "Недопустимый переход статуса"


class IdempotencyKeyReusedError(OrderError):
    code = "IDEMPOTENCY_KEY_REUSED"
    status_code = 409
    title = "Ключ идемпотентности уже использован"


class IdempotencyInProgressError(OrderError):
    code = "IDEMPOTENCY_IN_PROGRESS"
    status_code = 409
    title = "Создание заявки уже выполняется"


class CartScopeMismatchError(OrderError):
    code = "CART_SCOPE_MISMATCH"
    status_code = 409
    title = "Корзина другой организации"


class StaleResourceVersionError(OrderError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Ресурс изменился"


# Статусы, из которых клиент вправе отменить свою заявку.
CLIENT_CANCELABLE: set[OrderStatus] = {OrderStatus.NEW, OrderStatus.IN_PROGRESS}


def _merge_items(payload: OrderCreate) -> list[OrderItemCreate]:
    """Нормализует v1 payload перед fingerprint и stock validation."""
    merged: dict[str, OrderItemCreate] = {}
    for item in payload.items:
        existing = merged.get(item.sku)
        if existing is None:
            merged[item.sku] = item.model_copy(deep=True)
            continue
        existing.quantity += item.quantity
        if item.note and item.note != existing.note:
            existing.note = "\n".join(
                note for note in (existing.note, item.note) if note
            )
    return list(merged.values())


def order_request_fingerprint(
    payload: OrderCreate, *, organization_id: uuid.UUID | None = None
) -> str:
    """SHA-256 канонического payload, а не сырых JSON-байт запроса."""
    canonical = payload.model_dump(mode="json")
    canonical["organization_id"] = str(organization_id) if organization_id else None
    canonical["items"] = [
        item.model_dump(mode="json")
        for item in sorted(_merge_items(payload), key=lambda item: item.sku)
    ]
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def order_v2_request_fingerprint(
    payload: OrderCreateV2,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> str:
    """Canonical v2 fingerprint including actor, scope, endpoint, and payload."""
    canonical = payload.model_dump(mode="json")
    canonical["items"] = sorted(
        (item.model_dump(mode="json") for item in payload.items),
        key=lambda item: item["product_id"],
    )
    canonical.update(
        {
            "actor_user_id": str(user_id),
            "organization_id": str(organization_id) if organization_id else None,
            "endpoint": "/api/v2/orders",
        }
    )
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OrderService:
    """Жизненный цикл заявки: создание со снапшотом, списки, отмена, смена статуса."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricing = PricingService(db)
        self.organizations = OrganizationContextService(db)

    async def request_fingerprint(self, user, payload: OrderCreate) -> str:
        context = await self.organizations.resolve(user)
        return order_request_fingerprint(
            payload, organization_id=context.organization_id
        )

    async def find_idempotent_order(
        self, user, *, idempotency_key: str, request_hash: str
    ) -> Order | None:
        record = await orders_repo.get_idempotency_record(
            self.db, user_id=user.id, idempotency_key=idempotency_key
        )
        if record is None:
            return None
        if record.request_hash != request_hash:
            raise IdempotencyKeyReusedError(
                "Ключ Idempotency-Key уже использован с другими данными"
            )
        if record.order_id is None:
            raise IdempotencyInProgressError(
                "Заявка с этим ключом ещё создаётся; повторите запрос позже"
            )
        return await self.get(user, record.order_id, as_manager=False)

    async def reserve_idempotency(
        self, user, *, idempotency_key: str, request_hash: str
    ) -> OrderIdempotency | None:
        """Резервирует ключ; None означает конкурентный запрос с тем же ключом."""
        try:
            async with self.db.begin_nested():
                record = await orders_repo.add_idempotency_record(
                    self.db,
                    record=OrderIdempotency(
                        user_id=user.id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    ),
                )
            return record
        except IntegrityError:
            return None

    async def request_fingerprint_v2(
        self,
        user,
        payload: OrderCreateV2,
        *,
        context,
    ) -> str:
        return order_v2_request_fingerprint(
            payload,
            user_id=user.id,
            organization_id=context.organization_id,
        )

    async def create_v2(self, user, payload: OrderCreateV2, *, context) -> Order:
        """Create a UUID-based v2 order without changing v1 SKU semantics."""
        organization_id = context.organization_id
        resolved = await self.pricing.resolve_rate(
            user, "fixed", organization_id=organization_id
        )

        product_ids = [item.product_id for item in payload.items]
        products = await catalog_repo.get_by_ids_for_update(self.db, product_ids)
        for item in payload.items:
            product = products.get(item.product_id)
            if product is None:
                raise ProductNotFoundError(
                    f"Товар {item.product_id} не найден"
                )
            if product.stock_status == StockStatus.ARCHIVED:
                raise ProductUnavailableError(
                    f"Товар {product.sku} архивный — недоступен для заказа"
                )
            quantity = int(item.quantity)
            if product.stock_qty is not None and quantity > product.stock_qty:
                raise StockExceededError(product.sku, product.stock_qty)

        prices = await self.pricing.price_products(
            list(products.values()),
            user,
            "fixed",
            resolved=resolved,
            organization_id=organization_id,
        )
        new_items: list[OrderItem] = []
        total = Decimal(0)
        for item in payload.items:
            product = products[item.product_id]
            quantity = int(item.quantity)
            unit_price = Decimal(str(prices[product.id]["client_price"]))
            total += unit_price * quantity
            snapshot = {
                "sku": product.sku,
                "name": product.name,
                "brand_id": str(product.brand_id) if product.brand_id else None,
                "price_list_version_id": (
                    str(product.price_list_version_id)
                    if product.price_list_version_id
                    else None
                ),
            }
            new_items.append(
                OrderItem(
                    product_id=product.id,
                    product_snapshot=snapshot,
                    quantity=quantity,
                    unit_price=unit_price,
                    currency_code=resolved.currency,
                    note=item.note,
                )
            )

        delivery = payload.delivery
        delivery_address_id = delivery.address_id
        delivery_address_text = None
        if delivery.method == "DELIVERY" and delivery_address_id is not None:
            # Этап 2: адрес обязан принадлежать организации клиента; в заявку
            # пишется id и снапшот-строка (текст живёт в заявке, а не по FK).
            address = await organizations_repo.get_address(
                self.db,
                organization_id=organization_id,
                address_id=delivery_address_id,
            )
            if address is None:
                raise OrderAddressNotFoundError(
                    "Адрес доставки не найден в текущей организации"
                )
            delivery_address_text = ", ".join(
                part
                for part in (address.address_line, address.city, address.postal_code)
                if part
            )
        order = Order(
            client_id=user.id,
            organization_id=organization_id,
            status=OrderStatus.NEW,
            currency_code=resolved.currency,
            exchange_rate=(
                float(resolved.rate) if resolved.rate is not None else 1.0
            ),
            rate_source=resolved.source,
            total_amount=total.quantize(Decimal("0.01")),
            delivery_method=delivery.method.lower(),
            delivery_point=None,
            delivery_address=delivery_address_text,
            delivery_address_id=delivery_address_id,
            delivery_contact_name=delivery.contact_name,
            delivery_phone=delivery.phone,
            delivery_preferred_date=delivery.preferred_date,
            delivery_comment=delivery.comment,
            seq=await orders_repo.next_order_seq(self.db),
        )
        order = await orders_repo.create_order(self.db, order=order)
        for item in new_items:
            item.order_id = order.id
        await orders_repo.add_order_items(self.db, items=new_items)

        scoped_cart = await cart_repo.get_or_create_cart(
            self.db,
            user_id=user.id,
            organization_id=organization_id,
        )
        await cart_repo.clear_cart(self.db, cart_id=scoped_cart.id)
        await cart_repo.bump_cart_version(self.db, cart=scoped_cart)
        return order

    # -------------------------------------------------------------- create
    async def create(self, user, payload: OrderCreate) -> Order:
        """Оформление заявки: расчёт цен под клиента + снапшот + заморозка курса."""
        items = _merge_items(payload)
        context = await self.organizations.resolve(user)
        organization_id = context.organization_id

        resolved = await self.pricing.resolve_rate(
            user, payload.price_calc_mode, organization_id=organization_id
        )
        currency_code = resolved.currency
        exchange_rate = float(resolved.rate) if resolved.rate is not None else 1.0

        # 1) Товары одним IN-запросом с FOR UPDATE (аудит 2026-09-06):
        #    проверка остатка ниже и INSERT заявки проходят под блокировкой
        #    строк products — конкурентный заказ ждёт коммита первого и видит
        #    актуальный остаток (ORDER BY id в репозитории — без deadlock).
        skus = [ci.sku for ci in items]
        products = await catalog_repo.get_by_skus_for_update(self.db, skus)
        # Батч-цены: курс разрешён один раз выше, скидки по всем брендам —
        # одним запросом (было ~3 запроса на позицию).
        prices = await self.pricing.price_products(
            list(products.values()),
            user,
            payload.price_calc_mode,
            resolved=resolved,
            organization_id=organization_id,
        )

        new_items: list[OrderItem] = []
        total = 0.0
        for ci in items:
            product = products.get(ci.sku)
            if product is None:
                raise ProductNotFoundError(f"Товар {ci.sku} не найден")
            if product.stock_status == StockStatus.ARCHIVED:
                raise ProductUnavailableError(f"Товар {ci.sku} архивный — недоступен для заказа")
            # Остатки при заказе: если остаток задан (IS NOT NULL) — не даём
            # заказать больше доступного (NULL → остаток не отслеживается).
            if product.stock_qty is not None and ci.quantity > product.stock_qty:
                raise StockExceededError(ci.sku, product.stock_qty)
            unit_price = float(prices[product.id]["client_price"])
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
        delivery = payload.delivery
        delivery_method = delivery.method.lower() if delivery else payload.delivery_method
        delivery_point = (
            delivery.pickup_point
            if delivery and delivery.method == "PICKUP"
            else delivery.address
            if delivery
            else payload.delivery_point
        )
        order = Order(
            client_id=user.id,
            organization_id=organization_id,
            status=OrderStatus.NEW,
            currency_code=currency_code,
            exchange_rate=exchange_rate,
            rate_source=resolved.source,
            total_amount=round(total, 2),
            notes=payload.notes,
            delivery_method=delivery_method,
            delivery_point=delivery_point,
            delivery_address=delivery.address if delivery else None,
            delivery_contact_name=delivery.contact_name if delivery else None,
            delivery_phone=delivery.phone if delivery else None,
            delivery_preferred_date=delivery.preferred_date if delivery else None,
            delivery_comment=delivery.comment if delivery else None,
            seq=await orders_repo.next_order_seq(self.db),
        )
        order = await orders_repo.create_order(self.db, order=order)
        for item in new_items:
            item.order_id = order.id
        await orders_repo.add_order_items(self.db, items=new_items)

        # 3) Очищаем корзину в той же транзакции — атомарно с созданием заявки.
        #    Это гарантирует что корзина будет пуста даже если клиент закрыл вкладку
        #    до того как фронт успел вызвать DELETE /cart.
        user_cart = await cart_repo.get_or_create_cart(
            self.db, user_id=user.id, organization_id=None
        )
        await cart_repo.clear_cart(self.db, cart_id=user_cart.id)
        await cart_repo.bump_cart_version(self.db, cart=user_cart)

        return order

    # --------------------------------------------------------------- lists
    async def list_for_client(
        self, user, status: OrderStatus | None, page: int, per_page: int
    ) -> tuple[list[Order], int]:
        limit, offset = per_page, (page - 1) * per_page
        context = await self.organizations.resolve(user)
        rows = await orders_repo.fetch_orders(
            self.db,
            client_id=user.id,
            organization_id=context.organization_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await orders_repo.count_orders(
            self.db,
            client_id=user.id,
            organization_id=context.organization_id,
            status=status,
        )
        return rows, total

    async def list_for_client_v2(
        self,
        user,
        *,
        context,
        status: OrderStatus | None,
        limit: int,
        after: dict[str, str] | None,
        q: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_total: Decimal | None = None,
        max_total: Decimal | None = None,
    ) -> list[Order]:
        """Read-only v2 collection use-case with explicit commercial scope."""
        return await orders_repo.fetch_orders_v2_page(
            self.db,
            client_id=user.id,
            organization_id=context.organization_id,
            status=status,
            limit=limit,
            after=after,
            q=q,
            date_from=date_from,
            date_to=date_to,
            min_total=min_total,
            max_total=max_total,
        )

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
            raise OrderNotFoundError("Заявка не найдена")
        # Legacy orders remain user-owned; organization orders require an
        # explicit active membership. A non-owner contact is intentionally
        # allowed to read the organization's commercial order history.
        if not as_manager:
            if order.organization_id is None:
                if order.client_id != user.id:
                    raise OrderNotFoundError("Заявка не найдена")
            elif not await self.organizations.can_access(user, order.organization_id):
                raise OrderNotFoundError("Заявка не найдена")
        return order

    # -------------------------------------------------------------- repeat
    async def repeat(
        self, user, order_id: uuid.UUID, *, organization_id=None
    ) -> CartRead:
        """Повтор заказа (фича C): позиции старой заявки → корзину с АКТУАЛЬНЫМИ ценами."""
        order = await self.get(user, order_id, as_manager=False)
        # Organization orders must retain the commercial scope of the source
        # order even when a different organization is currently selected.
        # Legacy orders use the explicitly supplied context (v2) or legacy
        # user pricing (v1, when no scope is supplied).
        pricing_organization_id = order.organization_id or organization_id
        items = await orders_repo.get_order_items(self.db, order_id=order.id)
        cart_service = CartService(self.db)
        for item in items:
            sku = (item.product_snapshot or {}).get("sku")
            if not sku:
                continue
            try:
                await cart_service.add(
                    user,
                    sku,
                    item.quantity,
                    note=item.note,
                    organization_id=pricing_organization_id,
                )
            except ValueError:
                # Товар более недоступен (архив/удалён) — пропускаем тихо.
                continue
        return await cart_service.view(
            user, organization_id=pricing_organization_id
        )

    async def repeat_v2(
        self,
        user,
        order_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        expected_version: int,
    ) -> CartSummary:
        """Repeat into the active commercial cart with optimistic concurrency."""
        order = await self.get(user, order_id, as_manager=False)
        if (
            order.organization_id is not None
            and order.organization_id != organization_id
        ):
            raise CartScopeMismatchError(
                "Сначала переключитесь на организацию заявки и повторите действие"
            )

        order_items = await orders_repo.get_order_items(
            self.db, order_id=order.id
        )
        product_ids = [item.product_id for item in order_items if item.product_id]
        products = await catalog_repo.get_by_ids_for_update(self.db, product_ids)
        fallback_skus = [
            (item.product_snapshot or {}).get("sku")
            for item in order_items
            if item.product_id is None
        ]
        fallback_skus = [sku for sku in fallback_skus if sku]
        if fallback_skus:
            products.update(
                await catalog_repo.get_by_skus_for_update(self.db, fallback_skus)
            )

        cart_service = CartV2Service(self.db)
        cart, resolved = await cart_service.lock_for_mutation(
            user,
            organization_id=organization_id,
            expected_version=expected_version,
        )
        changed = False
        for item in order_items:
            product = products.get(item.product_id) if item.product_id else None
            if product is None:
                sku = (item.product_snapshot or {}).get("sku")
                product = next(
                    (
                        candidate
                        for candidate in products.values()
                        if candidate.sku == sku
                    ),
                    None,
                )
            if product is None or product.stock_status == StockStatus.ARCHIVED:
                continue
            existing = await cart_repo.get_cart_item(
                self.db, cart_id=cart.id, product_id=product.id
            )
            if (
                existing is not None
                and existing.quantity + item.quantity > MAX_DATABASE_INTEGER
            ):
                raise CartQuantityOverflowError(
                    "Суммарное количество позиции превышает максимум базы данных"
                )
            await cart_repo.upsert_cart_item(
                self.db,
                cart_id=cart.id,
                product_id=product.id,
                quantity=item.quantity,
                note=item.note,
            )
            changed = True
        if changed:
            await cart_repo.bump_cart_version(self.db, cart=cart)
        return await cart_service.project_locked(
            user,
            cart,
            organization_id=organization_id,
            resolved=resolved,
        )

    # -------------------------------------------------------------- cancel
    async def cancel(self, user, order_id: uuid.UUID) -> Order:
        order = await self.get(user, order_id, as_manager=False)
        if order.status not in CLIENT_CANCELABLE:
            raise OrderNotCancelableError("Заявку в этом статусе нельзя отменить")
        return await orders_repo.update_order_status(
            self.db, order=order, new_status=OrderStatus.CANCELLED
        )

    async def _ensure_available_for_confirmation(self, order: Order) -> None:
        """Повторно проверяет availability при подтверждении менеджером.

        Остаток здесь только проверяется: заявка не резервирует товар и не
        уменьшает stock_qty. Это сохраняет request-not-reservation semantics.
        """
        items = await orders_repo.get_order_items(self.db, order_id=order.id)
        product_ids = [item.product_id for item in items if item.product_id is not None]
        products = await catalog_repo.get_by_ids_for_update(self.db, product_ids)
        quantities: dict[uuid.UUID, int] = {}
        skus: dict[uuid.UUID, str] = {}
        for item in items:
            if item.product_id is None:
                continue
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
            skus[item.product_id] = (item.product_snapshot or {}).get("sku", str(item.product_id))
        for product_id, quantity in quantities.items():
            product = products.get(product_id)
            if product is None:
                raise ProductNotFoundError(f"Товар {skus[product_id]} не найден")
            if product.stock_status == StockStatus.ARCHIVED:
                raise ProductUnavailableError(
                    f"Товар {product.sku} архивный — недоступен для подтверждения"
                )
            if product.stock_qty is not None and quantity > product.stock_qty:
                raise StockExceededError(product.sku, product.stock_qty)

    # -------------------------------------------------------- change_status
    async def change_status(
        self,
        manager,
        order_id: uuid.UUID,
        new_status: OrderStatus,
        manager_id: uuid.UUID | None = None,
        expected_version: int | None = None,
    ) -> Order:
        order = await self.get(manager, order_id, as_manager=True)
        if expected_version is not None and order.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, актуальная версия {order.version}"
            )
        if new_status not in ALLOWED_TRANSITIONS[order.status]:
            raise InvalidOrderTransitionError(
                f"Запрещённый переход статуса: {order.status.value} → {new_status.value}"
            )
        if new_status == OrderStatus.IN_PROGRESS:
            await self._ensure_available_for_confirmation(order)
        before = {
            "status": order.status.value,
            "manager_id": str(order.manager_id) if order.manager_id else None,
            "version": order.version,
        }
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
                    "version": order.version + 1,
                },
            )
        )
        order.version += 1
        return await orders_repo.update_order_status(
            self.db, order=order, new_status=new_status, manager_id=manager_id
        )
