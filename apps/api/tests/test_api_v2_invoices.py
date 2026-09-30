"""Контрактные тесты API v2 «Счёт на оплату» (§16 п.40).

Покрывают канон:
  * 1:1 счёт↔заказ (второй POST → 409 ``INVOICE_ALREADY_EXISTS``,
    ``CANCELLED``-заказ → 409 ``ORDER_NOT_INVOICABLE``);
  * заморозка суммы и валюты заказа в счёте, номер ``СЧ-YYYY-NNNNNN``;
  * идемпотентность: тот же ``Idempotency-Key`` → тот же счёт
    (``X-Idempotency-Replayed: true``), тот же ключ на другом заказе →
    409 ``IDEMPOTENCY_KEY_REUSED``;
  * видимость: клиент видит счёт своего заказа (в detail и в списке), чужой
    клиент → 404 без утечки существования;
  * ``If-Match`` сверяет версию СЧЁТА: без заголовка → 400, устаревшая →
    409 ``STALE_RESOURCE_VERSION``, свежая → 200 и ``version + 1``;
  * скачивание PDF байтами с ``Content-Disposition`` (никогда presigned);
    неготовый PDF → 409, недоступное хранилище → 502.

Хранилище замокано (S3 в тестах не поднимается), задача рендера PDF тоже —
тесты не зависят от Celery/Redis.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text

from app.models.enums import (
    FileAssetType,
    FileVisibility,
    InvoicePdfStatus,
    InvoiceStatus,
    OrderStatus,
    OrganizationRole,
    UserRole,
)
from app.models.file import FileAsset
from app.models.invoice import Invoice
from app.models.order import Order, OrderItem
from app.models.organization import Organization
from app.models.system import AuditLog
from app.services import storage
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
)

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "v2-invoice-manager@example.by"
CLIENT_EMAIL = "v2-invoice-client@example.by"
OUTSIDER_EMAIL = "v2-invoice-outsider@example.by"


# --------------------------------------------------------------------- моки
@pytest.fixture(autouse=True)
def no_celery(monkeypatch):
    """Задача рендера PDF не должна ходить в Redis из тестов.

    Патчится символ в роутере: сервис импортирует ``enqueue_invoice_pdf``
    лениво, а роутер — по имени на этапе импорта модуля.
    """
    queued: list[str] = []

    def _fake_enqueue(invoice_id: uuid.UUID) -> None:
        queued.append(str(invoice_id))

    monkeypatch.setattr("app.api.v2.invoices.enqueue_invoice_pdf", _fake_enqueue)
    return queued


@pytest.fixture
def pdf_bytes(monkeypatch):
    """``storage.get_bytes`` отдаёт заранее заданный PDF-файл."""

    def _install(payload: bytes = b"%PDF-1.7 invoice") -> None:
        monkeypatch.setattr(
            "app.services.storage.get_bytes",
            lambda bucket, key: payload,
        )

    return _install


# ------------------------------------------------------------------ helpers
async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _logout(api_client) -> None:
    await api_client.post("/api/v1/auth/logout")


async def _seed_order(
    session_factory,
    *,
    client,
    product,
    organization_id=None,
    status: OrderStatus = OrderStatus.NEW,
    total: str = "40.00",
    currency: str = "BYN",
) -> Order:
    async with session_factory() as session:
        order = Order(
            client_id=client.id,
            organization_id=organization_id,
            status=status,
            currency_code=currency,
            exchange_rate="1.0000",
            rate_source="BYN",
            total_amount=total,
            delivery_method="pickup",
            delivery_point="Минск",
            created_at=datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc),
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_snapshot={"sku": product.sku, "name": product.name},
                quantity=4,
                unit_price="10.00",
                currency_code=currency,
                note="Строка счёта",
            )
        )
        await session.commit()
        await session.refresh(order)
        return order


async def _issue_invoice(
    api_client, order_id: uuid.UUID, *, key: str = "inv-key-1"
) -> tuple[int, dict, dict]:
    return await api_client.post(
        f"/api/v2/manager/orders/{order_id}/invoice",
        headers={"Idempotency-Key": key},
    )


async def _seed_invoice(
    session_factory, *, order, manager, pdf: bool = False
) -> Invoice:
    """Счёт напрямую в БД — для сценариев чтения/скачивания."""
    async with session_factory() as session:
        invoice = Invoice(
            order_id=order.id,
            seq=await _next_seq(session),
            number="СЧ-2026-000042",
            status=InvoiceStatus.ISSUED,
            pdf_status=InvoicePdfStatus.PENDING,
            total_amount=order.total_amount,
            currency_code=order.currency_code,
            issued_at=datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc),
            created_by=manager.id if manager is not None else None,
            version=1,
        )
        session.add(invoice)
        await session.flush()

        if pdf:
            asset = FileAsset(
                type=FileAssetType.INVOICE_PDF,
                s3_key=f"invoices/invoice-{invoice.seq}.pdf",
                filename_display=f"{invoice.number}.pdf",
                content_type="application/pdf",
                size_bytes=19,
                order_id=order.id,
                visibility=FileVisibility.AUTHED,
            )
            session.add(asset)
            await session.flush()
            invoice.pdf_file_asset_id = asset.id
            invoice.pdf_status = InvoicePdfStatus.READY

        await session.commit()
        await session.refresh(invoice)
        return invoice


async def _next_seq(session) -> int:
    return (
        await session.execute(text("SELECT nextval('invoices_seq_seq')"))
    ).scalar_one()


# ===========================================================================
# Выдача счёта менеджером
# ===========================================================================
async def test_manager_issues_invoice_with_frozen_totals(api_client, session_factory):
    manager = await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Invoice Brand")
    product = await create_product(
        session_factory,
        sku="V2-INV-1",
        name="Invoice product",
        brand=brand,
        base_price=10,
    )
    organization = await create_organization(
        session_factory, legal_name="ООО Покупатель", display_name="Покупатель"
    )
    await add_organization_membership(
        session_factory,
        user=client,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    order = await _seed_order(
        session_factory,
        client=client,
        product=product,
        organization_id=organization.id,
        total="1234.56",
        currency="BYN",
    )
    await set_active_organization(
        session_factory, user=client, organization=organization
    )
    await _login(api_client, MANAGER_EMAIL)

    response = await _issue_invoice(api_client, order.id)

    assert response.status_code == 201, response.text
    body = response.json()
    invoice = body["data"]
    assert invoice["orderId"] == str(order.id)
    assert invoice["status"] == "ISSUED"
    # PDF ещё не отрисован — состояние в БД, не в Redis (§16 п.40 п.5).
    assert invoice["pdfStatus"] == "PENDING"
    # Заморозка суммы и валюты заказа на момент выставления.
    assert invoice["total"] == {"amount": "1234.56", "currency": "BYN"}
    assert invoice["version"] == 1
    assert invoice["dueAt"] is None
    assert invoice["issuedAt"].endswith("Z") or "+00:00" in invoice["issuedAt"]
    # Номер СЧ-YYYY-NNNNNN (§16 п.40 п.2).
    number = invoice["number"]
    prefix, year, seq = number.split("-")
    assert prefix == "СЧ"
    assert len(year) == 4 and year.isdigit()
    assert len(seq) == 6 and seq.isdigit()
    # Реквизиты: покупатель — из organizations, продавец — из конфигурации.
    assert invoice["buyer"]["legalName"] == "ООО Покупатель"
    assert "legalName" in invoice["seller"]
    # S3-ключи и внутренние идентификаторы наружу не утекают.
    assert "s3" not in response.text.lower()
    assert "createdBy" not in response.text
    assert response.headers["X-Idempotency-Replayed"] == "false"

    # Счёт лёг в БД с тем же номером и суммой.
    async with session_factory() as session:
        stored = await session.get(Invoice, uuid.UUID(invoice["id"]))
        assert stored is not None
        assert stored.number == number
        assert str(stored.total_amount) == "1234.56"
        assert stored.pdf_status == InvoicePdfStatus.PENDING
        assert stored.created_by == manager.id
        assert stored.seq == int(seq)


async def test_repeated_post_with_new_key_conflicts(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Dup Brand")
    product = await create_product(
        session_factory, sku="V2-INV-DUP", name="Dup product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    await _login(api_client, MANAGER_EMAIL)

    first = await _issue_invoice(api_client, order.id, key="inv-dup-1")
    assert first.status_code == 201, first.text

    # Новый ключ, тот же заказ — 1:1 запрещён, тихо вернуть тот же счёт нельзя.
    second = await _issue_invoice(api_client, order.id, key="inv-dup-2")
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    assert second.json()["code"] == "INVOICE_ALREADY_EXISTS"

    # Ровно один счёт на заказ — гонка не плодит дубли.
    async with session_factory() as session:
        total = (
            await session.execute(
                select(func.count()).select_from(Invoice).where(Invoice.order_id == order.id)
            )
        ).scalar_one()
    assert total == 1


async def test_same_idempotency_key_replays_same_invoice(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Replay Brand")
    product = await create_product(
        session_factory, sku="V2-INV-RPL", name="Replay product", brand=brand, base_price=10
    )
    first_order = await _seed_order(session_factory, client=client, product=product)
    second_order = await _seed_order(session_factory, client=client, product=product)
    await _login(api_client, MANAGER_EMAIL)

    created = await _issue_invoice(api_client, first_order.id, key="inv-replay")
    assert created.status_code == 201, created.text
    created_id = created.json()["data"]["id"]

    replay = await _issue_invoice(api_client, first_order.id, key="inv-replay")
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["id"] == created_id
    assert replay.headers["X-Idempotency-Replayed"] == "true"

    # Тот же ключ на другом заказе — не тихая выдача чужого счёта.
    reused = await _issue_invoice(api_client, second_order.id, key="inv-replay")
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_cancelled_order_is_not_invoicable(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Cancel Brand")
    product = await create_product(
        session_factory, sku="V2-INV-CXL", name="Cancel product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory,
        client=client,
        product=product,
        status=OrderStatus.CANCELLED,
    )
    await _login(api_client, MANAGER_EMAIL)

    response = await _issue_invoice(api_client, order.id)

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "ORDER_NOT_INVOICABLE"


async def test_issue_invoice_unknown_order_is_404(api_client, session_factory):
    """Несуществующий заказ → 404 ORDER_NOT_FOUND, а не 400 «ошибка счёта»."""
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    await _login(api_client, MANAGER_EMAIL)

    response = await _issue_invoice(api_client, uuid.uuid4(), key="inv-key-unknown")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "ORDER_NOT_FOUND"


async def test_issue_invoice_requires_manager_role(api_client, session_factory):
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Role Brand")
    product = await create_product(
        session_factory, sku="V2-INV-ROLE", name="Role product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    await _login(api_client, CLIENT_EMAIL)

    response = await _issue_invoice(api_client, order.id)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_issue_invoice_requires_idempotency_key(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Key Brand")
    product = await create_product(
        session_factory, sku="V2-INV-KEY", name="Key product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    await _login(api_client, MANAGER_EMAIL)

    missing = await api_client.post(f"/api/v2/manager/orders/{order.id}/invoice")
    assert missing.status_code == 422
    assert missing.json()["code"] == "VALIDATION_ERROR"

    invalid = await api_client.post(
        f"/api/v2/manager/orders/{order.id}/invoice",
        headers={"Idempotency-Key": "x" * 256},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_ERROR"


# ===========================================================================
# Видимость счёта клиентом
# ===========================================================================
async def test_client_sees_invoice_in_order_detail_and_downloads_pdf(
    api_client, session_factory, pdf_bytes
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Client Brand")
    product = await create_product(
        session_factory, sku="V2-INV-CLI", name="Client product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(session_factory, order=order, manager=None, pdf=True)
    pdf_bytes(b"%PDF-1.7 hello-invoice")
    await _login(api_client, CLIENT_EMAIL)

    detail = await api_client.get(f"/api/v2/orders/{order.id}")
    assert detail.status_code == 200, detail.text
    embedded = detail.json()["data"]["invoice"]
    assert embedded["id"] == str(invoice.id)
    assert embedded["number"] == invoice.number
    assert embedded["status"] == "ISSUED"
    assert embedded["pdfStatus"] == "READY"
    assert embedded["total"] == {"amount": "40.00", "currency": "BYN"}

    # Счёт в коллекции — краткая форма, без сумм и реквизитов.
    listing = await api_client.get("/api/v2/orders")
    assert listing.status_code == 200, listing.text
    row = next(
        item
        for item in listing.json()["data"]
        if item["id"] == str(order.id)
    )
    assert set(row["invoice"]) == {"id", "number", "status"}

    direct = await api_client.get(f"/api/v2/orders/{order.id}/invoice")
    assert direct.status_code == 200, direct.text
    assert direct.json()["data"]["id"] == str(invoice.id)

    # Скачивание байтами + Content-Disposition; presigned-URL не используется.
    download = await api_client.get(f"/api/v2/orders/invoices/{invoice.id}/download")
    assert download.status_code == 200, download.text
    assert download.content == b"%PDF-1.7 hello-invoice"
    assert download.headers["content-type"] == "application/pdf"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition
    # Наружу не отдаём ни presigned-URL, ни ключ бакета.
    assert "http" not in download.headers["content-disposition"]


async def test_outsider_client_gets_404_for_invoice_and_download(
    api_client, session_factory
):
    manager = await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await create_user(
        session_factory, email=OUTSIDER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Outsider Brand")
    product = await create_product(
        session_factory,
        sku="V2-INV-OUT",
        name="Outsider product",
        brand=brand,
        base_price=10,
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(
        session_factory, order=order, manager=manager, pdf=True
    )
    await _login(api_client, OUTSIDER_EMAIL)

    detail = await api_client.get(f"/api/v2/orders/{order.id}/invoice")
    assert detail.status_code == 404
    assert detail.json()["code"] == "INVOICE_NOT_FOUND"

    download = await api_client.get(f"/api/v2/orders/invoices/{invoice.id}/download")
    assert download.status_code == 404
    assert download.json()["code"] == "INVOICE_NOT_FOUND"

    # Чужой счёт не проскальзывает и в detail чужого заказа (заказ тоже 404).
    order_detail = await api_client.get(f"/api/v2/orders/{order.id}")
    assert order_detail.status_code == 404


async def test_download_pdf_not_ready_conflicts(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Pending Brand")
    product = await create_product(
        session_factory, sku="V2-INV-PND", name="Pending product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(session_factory, order=order, manager=None, pdf=False)
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.get(f"/api/v2/orders/invoices/{invoice.id}/download")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INVOICE_PDF_NOT_READY"


async def test_download_storage_unavailable_is_502(api_client, session_factory, monkeypatch):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Storage Brand")
    product = await create_product(
        session_factory,
        sku="V2-INV-STO",
        name="Storage product",
        brand=brand,
        base_price=10,
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(
        session_factory, order=order, manager=None, pdf=True
    )

    def _boom(bucket, key):
        raise storage.StorageError("minio недоступен")

    monkeypatch.setattr("app.services.storage.get_bytes", _boom)
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.get(f"/api/v2/orders/invoices/{invoice.id}/download")

    assert response.status_code == 502
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"


# ===========================================================================
# Перерендер PDF
# ===========================================================================
async def test_regenerate_pdf_sets_pending_and_enqueues(api_client, session_factory, no_celery):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Regen Brand")
    product = await create_product(
        session_factory, sku="V2-INV-REG", name="Regen product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(session_factory, order=order, manager=None, pdf=False)
    async with session_factory() as session:
        stored = await session.get(Invoice, invoice.id)
        stored.pdf_status = InvoicePdfStatus.FAILED
        await session.commit()
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.post(f"/api/v2/manager/invoices/{invoice.id}/pdf")

    assert response.status_code == 202, response.text
    assert response.json()["data"]["pdfStatus"] == "PENDING"
    assert no_celery == [str(invoice.id)]

    async with session_factory() as session:
        stored = await session.get(Invoice, invoice.id)
        assert stored.pdf_status == InvoicePdfStatus.PENDING


async def test_regenerate_pdf_rejects_concurrent_render(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Regen Busy Brand")
    product = await create_product(
        session_factory, sku="V2-INV-BSY", name="Regen busy product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(session_factory, order=order, manager=None, pdf=False)
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.post(f"/api/v2/manager/invoices/{invoice.id}/pdf")

    assert response.status_code == 409
    assert response.json()["code"] == "INVOICE_PDF_IN_PROGRESS"


# ===========================================================================
# Смена статуса счёта (If-Match по версии счёта)
# ===========================================================================
async def _invoice_for_manager(session_factory, *, product_brand=None):
    manager = await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    client = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = product_brand or await create_brand(session_factory, name="Status Brand")
    product = await create_product(
        session_factory, sku="V2-INV-ST", name="Status product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=client, product=product)
    invoice = await _seed_invoice(session_factory, order=order, manager=manager)
    return manager, order, invoice


async def test_change_invoice_status_requires_if_match(api_client, session_factory):
    _, _, invoice = await _invoice_for_manager(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    missing = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}", json={"status": "PAID"}
    )
    assert missing.status_code == 400
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "INVALID_IF_MATCH"

    malformed = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "PAID"},
        headers={"If-Match": "not-a-version"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "INVALID_IF_MATCH"


async def test_change_invoice_status_rejects_stale_version(api_client, session_factory):
    _, _, invoice = await _invoice_for_manager(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "PAID"},
        headers={"If-Match": "99"},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "STALE_RESOURCE_VERSION"


async def test_change_invoice_status_bumps_version_and_audits(
    api_client, session_factory
):
    manager, _, invoice = await _invoice_for_manager(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    fresh = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "PAID"},
        headers={"If-Match": str(invoice.version)},
    )

    assert fresh.status_code == 200, fresh.text
    body = fresh.json()["data"]
    assert body["status"] == "PAID"
    assert body["version"] == invoice.version + 1

    async with session_factory() as session:
        stored = await session.get(Invoice, invoice.id)
        assert stored.status == InvoiceStatus.PAID
        assert stored.version == invoice.version + 1

        audits = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "invoice",
                    AuditLog.target_id == invoice.id,
                    AuditLog.action == "invoice.update",
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].actor_id == manager.id
        assert audits[0].before is not None
        assert audits[0].after is not None

    # Повтор того же If-Match теперь устарел.
    stale = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "CANCELLED"},
        headers={"If-Match": str(invoice.version)},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"


async def test_change_invoice_status_rejects_invalid_transition(
    api_client, session_factory
):
    _, _, invoice = await _invoice_for_manager(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "NOT_A_STATUS"},
        headers={"If-Match": str(invoice.version)},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_change_invoice_status_requires_manager(api_client, session_factory):
    _, _, invoice = await _invoice_for_manager(session_factory)
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.patch(
        f"/api/v2/manager/invoices/{invoice.id}",
        json={"status": "PAID"},
        headers={"If-Match": str(invoice.version)},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


# ===========================================================================
# Реквизиты организации (PATCH /manager/organizations/{id})
# ===========================================================================
async def test_manager_updates_organization_billing_requisites(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    organization = await create_organization(
        session_factory, legal_name="ООО Реквизиты"
    )
    await _login(api_client, MANAGER_EMAIL)

    async with session_factory() as session:
        stored = await session.get(Organization, organization.id)
        current_version = stored.version

    stale = await api_client.patch(
        f"/api/v2/manager/organizations/{organization.id}",
        json={"bankName": "Приорбанк"},
        headers={"If-Match": str(current_version + 5)},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"

    response = await api_client.patch(
        f"/api/v2/manager/organizations/{organization.id}",
        json={
            "taxId": "770000000",
            "legalAddress": "220030, Минск, ул. Ленина, 1",
            "bankName": "Приорбанк",
            "bankCode": "POISBY2X",
            "bankAccount": "BY11POIS30000000000000000000POIS",
        },
        headers={"If-Match": str(current_version)},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["bankName"] == "Приорбанк"
    assert body["bankCode"] == "POISBY2X"
    assert body["bankAccount"] == "BY11POIS30000000000000000000POIS"
    assert body["version"] == current_version + 1

    # Реквизиты попадают в проекцию покупателя счёта.
    async with session_factory() as session:
        stored = await session.get(Organization, organization.id)
        assert stored.bank_name == "Приорбанк"
        assert stored.tax_id == "770000000"
        assert stored.version == current_version + 1


async def test_organization_billing_patch_requires_manager(api_client, session_factory):
    await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(
        session_factory, legal_name="ООО Чужой менеджер"
    )
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.patch(
        f"/api/v2/manager/organizations/{organization.id}",
        json={"bankName": "Хак"},
        headers={"If-Match": "1"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
