"""NOTIF-01: триггеры in-app уведомлений о бизнес-событиях.

Слои:
  1. ``ORDER_STATUS_CHANGED`` — PATCH /manager/orders: уведомление клиенту
     создаётся транзакционно со сменой статуса, SSE-публикация — после коммита;
     запрещённый переход — уведомления нет;
  2. ``INVOICE_ISSUED`` — InvoiceService.issue: уведомление клиенту в той же
     транзакции, что и счёт;
  3. ``IMPORT_DONE`` — _finalize (успех и SchemaError = DONE с одной ошибкой):
     broadcast менеджерам; ``IMPORT_FAILED`` — _mark_failed и beat-reconciler
     (reconcile зовёт _mark_failed — один broadcast на переход в FAILED).

SSE-публикация подменяется рекордером на уровне модулей-владельцев
(services.order / services.invoice / tasks.import_price_list), как в
test_notification_events / test_notification_dispatch_idempotency.
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

import app.services.invoice as invoice_service_module
import app.services.order as order_service_module
import app.tasks.import_price_list as import_task
from app.models.catalog import PriceListVersion
from app.models.enums import ImportMode, OrderStatus, PriceListVersionStatus, UserRole
from app.models.order import Order
from app.models.system import Notification
from app.services.invoice import InvoiceService
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "notif-client@example.by"
MANAGER_EMAIL = "notif-manager@example.by"


class _PublishSpy:
    """Рекордер publish_notification: (payload, user_id)."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, uuid.UUID | None]] = []

    def __call__(self, payload: dict, user_id: uuid.UUID | None) -> None:
        self.calls.append((payload, user_id))


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed_and_order(sf, api_client):
    """Каталог + клиент + менеджер + заявка клиента (как в test_manager_orders)."""
    brand = await create_brand(sf, name="NotifBrand")
    series = await create_series(sf, brand=brand, name="NotifSerie")
    await create_product(sf, sku="N-1", name="Widget", brand=brand, series=series, base_price=100)
    client = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)

    await _login(api_client, CLIENT_EMAIL)
    order_id = (
        await api_client.post(
            "/api/v1/orders",
            json={"items": [{"sku": "N-1", "quantity": 2}],
                  "delivery_point": "Склад Минск"},
        )
    ).json()["id"]
    return order_id, client


async def _notifications_of_type(sf, type_: str) -> list[Notification]:
    async with sf() as s:
        return list(
            (await s.scalars(select(Notification).where(Notification.type == type_))).all()
        )


# ===========================================================================
# 1. ORDER_STATUS_CHANGED
# ===========================================================================
class TestOrderStatusChanged:
    async def test_valid_transition_notifies_client_after_commit(
        self, api_client, session_factory, monkeypatch
    ):
        sf = session_factory
        order_id, client = await _seed_and_order(sf, api_client)
        await _login(api_client, MANAGER_EMAIL)

        spy = _PublishSpy()
        monkeypatch.setattr(order_service_module, "publish_notification", spy)

        r = await api_client.patch(
            f"/api/v1/manager/orders/{order_id}", json={"status": "IN_PROGRESS"}
        )
        assert r.status_code == 200, r.text

        notifs = await _notifications_of_type(sf, "ORDER_STATUS_CHANGED")
        assert len(notifs) == 1  # ровно одна на смену статуса
        notif = notifs[0]
        assert notif.user_id == client.id  # адресат — клиент, не менеджер
        order_number = r.json()["seq"]
        assert f"#{order_number:06d}" in notif.body
        assert "В работе" in notif.body  # статус в RU (ORDER_STATUS_RU)
        assert notif.payload == {
            "order_id": order_id,
            "order_number": f"#{order_number:06d}",
            "old_status": "NEW",
            "new_status": "IN_PROGRESS",
        }
        # SSE-событие клиенту — ровно одно, на персональный канал.
        assert len(spy.calls) == 1
        payload, user_id = spy.calls[0]
        assert user_id == client.id
        assert payload["type"] == "ORDER_STATUS_CHANGED"
        assert payload["id"] == str(notif.id)

    async def test_invalid_transition_creates_no_notification(
        self, api_client, session_factory, monkeypatch
    ):
        sf = session_factory
        order_id, _client = await _seed_and_order(sf, api_client)
        await _login(api_client, MANAGER_EMAIL)

        spy = _PublishSpy()
        monkeypatch.setattr(order_service_module, "publish_notification", spy)

        # NEW → COMPLETED запрещён FSM (ALLOWED_TRANSITIONS, §9).
        r = await api_client.patch(
            f"/api/v1/manager/orders/{order_id}", json={"status": "COMPLETED"}
        )
        assert r.status_code == 409
        assert await _notifications_of_type(sf, "ORDER_STATUS_CHANGED") == []
        assert spy.calls == []  # публикация не вызывалась вовсе


# ===========================================================================
# 2. INVOICE_ISSUED (через сервис, как в test_api_v2_invoices)
# ===========================================================================
async def _seed_order(sf, *, client, seq: int = 12345) -> Order:
    async with sf() as s:
        order = Order(
            client_id=client.id,
            seq=seq,
            status=OrderStatus.NEW,
            currency_code="BYN",
            exchange_rate=Decimal("1"),
            total_amount=Decimal("150.50"),
            delivery_method="pickup",
        )
        s.add(order)
        await s.commit()
        await s.refresh(order)
        return order


class TestInvoiceIssued:
    async def test_issue_notifies_client_in_same_transaction(
        self, session_factory, monkeypatch
    ):
        sf = session_factory
        client = await create_user(sf, email="inv-client@x.by", role=UserRole.CLIENT)
        manager = await create_user(sf, email="inv-manager@x.by", role=UserRole.MANAGER)
        order = await _seed_order(sf, client=client)

        spy = _PublishSpy()
        monkeypatch.setattr(invoice_service_module, "publish_notification", spy)

        async with sf() as db:
            # Инстанс сервиса сохраняем: SSE-публикацию после коммита выполняет
            # роутер через publish_status_notification() — здесь роль роутера.
            svc = InvoiceService(db)
            invoice = await svc.issue(manager, order.id)
            # Уведомление уже видно ВНУТРИ той же транзакции (flush без commit).
            staged = await db.scalar(
                select(Notification).where(Notification.type == "INVOICE_ISSUED")
            )
            assert staged is not None
            await db.commit()
            svc.publish_status_notification()
            invoice_id, invoice_number = invoice.id, invoice.number

        notifs = await _notifications_of_type(sf, "INVOICE_ISSUED")
        assert len(notifs) == 1
        notif = notifs[0]
        assert notif.user_id == client.id
        assert invoice_number in notif.body  # «СЧ-YYYY-NNNNNN»
        assert "150.50" in notif.body and "BYN" in notif.body
        assert notif.payload == {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "order_id": str(order.id),
            "amount": "150.50",  # Decimal в payload — строкой (§8)
            "currency": "BYN",
        }
        assert len(spy.calls) == 1
        payload, user_id = spy.calls[0]
        assert user_id == client.id
        assert payload["type"] == "INVOICE_ISSUED"


# ===========================================================================
# 3. IMPORT_DONE / IMPORT_FAILED (broadcast менеджерам, user_id=None)
# ===========================================================================
async def _seed_version(sf, *, status, started_at=None) -> PriceListVersion:
    uploader = await create_user(sf, email="uploader@x.by", role=UserRole.MANAGER)
    async with sf() as s:
        v = PriceListVersion(
            uploaded_by=uploader.id,
            filename="prices.csv",
            import_mode=ImportMode.UPSERT,
            status=status,
            base_currency="BYN",
            rate_to_byn=1,
            rate_source="MANUAL",
            started_at=started_at,
        )
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


class TestImportNotifications:
    async def test_finalize_done_creates_broadcast(self, session_factory, monkeypatch):
        sf = session_factory
        version = await _seed_version(sf, status=PriceListVersionStatus.PROCESSING)
        spy = _PublishSpy()
        monkeypatch.setattr(import_task, "publish_notification", spy)

        async with sf() as db:
            v = await db.get(PriceListVersion, version.id)
            await import_task._finalize(db, v, ok=640, err=2, total=642, errors=[])
            await db.commit()

        notifs = await _notifications_of_type(sf, "IMPORT_DONE")
        assert len(notifs) == 1
        notif = notifs[0]
        assert notif.user_id is None  # broadcast менеджерам
        assert "prices.csv" in notif.body and "640" in notif.body
        assert notif.payload == {
            "version_id": str(version.id),
            "filename": "prices.csv",
            "rows_ok": 640,
            "rows_error": 2,
            "rows_total": 642,
        }
        assert len(spy.calls) == 1 and spy.calls[0][1] is None

    async def test_finalize_schema_error_variant_is_done_broadcast(
        self, session_factory, monkeypatch
    ):
        """SchemaError проходит через _finalize: DONE + IMPORT_DONE с err=1."""
        sf = session_factory
        version = await _seed_version(sf, status=PriceListVersionStatus.PROCESSING)
        monkeypatch.setattr(import_task, "publish_notification", _PublishSpy())

        async with sf() as db:
            v = await db.get(PriceListVersion, version.id)
            await import_task._finalize(db, v, ok=0, err=1, total=0, errors=[])
            await db.commit()

        notifs = await _notifications_of_type(sf, "IMPORT_DONE")
        assert len(notifs) == 1 and notifs[0].payload["rows_error"] == 1

    async def test_mark_failed_creates_broadcast(self, session_factory, monkeypatch):
        sf = session_factory
        version = await _seed_version(sf, status=PriceListVersionStatus.PROCESSING)
        spy = _PublishSpy()
        monkeypatch.setattr(import_task, "publish_notification", spy)
        # _mark_failed открывает свою сессию через _worker_session — подменяем
        # на тестовую (как в test_import_reliability).
        monkeypatch.setattr(import_task, "_worker_session", sf)

        await import_task._mark_failed(version.id, "S3 недоступен")

        notifs = await _notifications_of_type(sf, "IMPORT_FAILED")
        assert len(notifs) == 1
        notif = notifs[0]
        assert notif.user_id is None
        assert notif.payload == {
            "version_id": str(version.id),
            "filename": "prices.csv",
            "reason": "S3 недоступен",
        }
        assert len(spy.calls) == 1 and spy.calls[0][1] is None

    async def test_reconcile_stuck_creates_failed_broadcast(
        self, session_factory, monkeypatch
    ):
        """Beat-reconciler переводит зависшую PROCESSING в FAILED → IMPORT_FAILED."""
        sf = session_factory
        stale_started = datetime.now(UTC) - timedelta(
            hours=import_task.STUCK_IMPORT_HOURS + 1
        )
        version = await _seed_version(
            sf, status=PriceListVersionStatus.PROCESSING, started_at=stale_started
        )
        monkeypatch.setattr(import_task, "_worker_session", sf)
        spy = _PublishSpy()
        monkeypatch.setattr(import_task, "publish_notification", spy)

        result = await import_task._reconcile_stuck()

        assert result == {"status": "ok", "reconciled": 1}
        notifs = await _notifications_of_type(sf, "IMPORT_FAILED")
        assert len(notifs) == 1
        assert notifs[0].user_id is None
        assert notifs[0].payload["version_id"] == str(version.id)
        assert "воркер" in notifs[0].payload["reason"]


# ===========================================================================
# 5. NEW_ORDER — broadcast менеджерам при создании заявки (§20.3)
# ===========================================================================
class TestNewOrder:
    async def test_create_notifies_managers_broadcast(
        self, api_client, session_factory, monkeypatch
    ):
        sf = session_factory
        brand = await create_brand(sf, name="NewOrderBrand")
        series = await create_series(sf, brand=brand, name="NewOrderSerie")
        await create_product(sf, sku="NO-1", name="Widget", brand=brand, series=series, base_price=100)
        client = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
        await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)

        await _login(api_client, CLIENT_EMAIL)
        spy = _PublishSpy()
        monkeypatch.setattr(order_service_module, "publish_notification", spy)

        r = await api_client.post(
            "/api/v1/orders",
            json={"items": [{"sku": "NO-1", "quantity": 2}],
                  "delivery_point": "Склад Минск"},
        )
        assert r.status_code == 201, r.text
        seq = r.json()["seq"]

        notifs = await _notifications_of_type(sf, "NEW_ORDER")
        assert len(notifs) == 1
        notif = notifs[0]
        assert notif.user_id is None  # broadcast: видят все менеджеры
        # create_user строит full_name из email → "Client"
        assert client.full_name in notif.body
        assert f"#{seq:06d}" in notif.body
        assert "200.00" in notif.body  # 2 × 100.00, quantize_money
        assert notif.payload["items_count"] == 1  # позиций (не штук): 1 × qty 2
        # SSE — ровно одно broadcast-событие
        assert len(spy.calls) == 1
        payload, user_id = spy.calls[0]
        assert user_id is None
        assert payload["type"] == "NEW_ORDER"
        assert payload["id"] == str(notif.id)
