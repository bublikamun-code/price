"""Контрактные тесты API v2 «Коммерческие предложения» (этап 8 роадмапа).

Покрывают канон:
  * create DRAFT: version=1, total не заморожен (равен сумме позиций), номера нет;
  * send: без valid_until → 400 ``QUOTE_VALID_UNTIL_REQUIRED``; с ним → SENT,
    номер ``КП-YYYY-NNNNNN``, total заморожен;
  * видимость: клиент видит КП своей организации, чужая org → 404, DRAFT → 404;
  * accept: заявка создана с ЦЕНАМИ ИЗ КП (override, не базовая цена),
    approval по настройкам организации; тот же Idempotency-Key → replay,
    второй accept (другой ключ) → 409 ``QUOTE_STATE_CHANGED``;
  * истёкший valid_until → 409 ``QUOTE_EXPIRED``; reject → REJECTED, accept
    после reject → 409;
  * RBAC: клиент на /manager/quotes → 403, аноним на /quotes → 401;
  * PDF: синхронный рендер → READY, скачивание байтами с ``%PDF``-магией;
  * PATCH DRAFT меняет items → version+1; PATCH SENT → 409.

Хранилище и weasyprint замоканы (S3/Pango в тестах не поднимаются); Celery
не используется — рендер КП синхронный, как и скачивание.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.enums import (
    ApprovalMode,
    ApprovalStatus,
    OrganizationRole,
    QuotePdfStatus,
    QuoteStatus,
    UserRole,
)
from app.models.order import Order, OrderItem
from app.models.quote import Quote
from app.models.system import AuditLog, Notification
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
    set_organization_approval,
)

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "v2-quote-manager@example.by"
CLIENT_EMAIL = "v2-quote-client@example.by"
OUTSIDER_EMAIL = "v2-quote-outsider@example.by"

# Срок действия по умолчанию — «далеко» в будущем от любой точки 2026 года.
DEFAULT_VALID_UNTIL = "2027-12-31T23:59:59+00:00"


# --------------------------------------------------------------------- моки
@pytest.fixture
def pdf_mock(monkeypatch):
    """weasyprint + S3 замоканы: рендер возвращает фиксированные ``%PDF``-байты,
    upload/get_bytes работают с памятью. Возвращает захваченное состояние."""
    state: dict = {"bytes": b"%PDF-1.7 quote", "uploads": []}

    monkeypatch.setattr("app.core.pdf.write_pdf", lambda html: state["bytes"])

    def _upload(bucket, key, fileobj, content_type="application/octet-stream"):
        state["uploads"].append({"bucket": bucket, "key": key})
        fileobj.read()

    monkeypatch.setattr("app.services.storage.upload_fileobj", _upload)
    monkeypatch.setattr(
        "app.services.storage.get_bytes", lambda bucket, key: state["bytes"]
    )
    return state


# ------------------------------------------------------------------ helpers
async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _logout(api_client) -> None:
    await api_client.post("/api/v1/auth/logout")


async def _seed_client_with_org(
    session_factory, *, email: str = CLIENT_EMAIL, approval: ApprovalMode | None = None
):
    """Клиент + организация + активное членство BUYER (опц. режим визы)."""
    client = await create_user(
        session_factory, email=email, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(
        session_factory, legal_name=f"ООО {email.split('@')[0]}"
    )
    await add_organization_membership(
        session_factory,
        user=client,
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    await set_active_organization(session_factory, user=client, organization=organization)
    if approval is not None:
        await set_organization_approval(
            session_factory, organization=organization, mode=approval
        )
    return client, organization


def _quote_payload(
    organization_id, products_prices: list[tuple], *, valid_until: str | None = DEFAULT_VALID_UNTIL
) -> dict:
    """products_prices: [(product_id, qty, "77.50", "Комментарий"), ...]."""
    body: dict = {
        "organizationId": str(organization_id),
        "items": [
            {
                "productId": str(product_id),
                "quantity": qty,
                "unitPrice": {"amount": price, "currency": "BYN"},
                "comment": comment,
            }
            for product_id, qty, price, comment in products_prices
        ],
    }
    if valid_until is not None:
        body["validUntil"] = valid_until
    return body


async def _create_quote(api_client, organization, products_prices, *, valid_until=DEFAULT_VALID_UNTIL):
    response = await api_client.post(
        "/api/v2/manager/quotes",
        json=_quote_payload(
            organization.id, products_prices, valid_until=valid_until
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _send_quote(api_client, quote_id: str, *, if_match: str = "1"):
    return await api_client.post(
        f"/api/v2/manager/quotes/{quote_id}/send",
        headers={"If-Match": if_match},
    )


async def _accept(api_client, quote_id: str, *, key: str, delivery: dict | None = None):
    body = delivery or {
        "delivery": {
            "method": "PICKUP",
            "contactName": "Иван",
            "phone": "+375291234567",
        }
    }
    return await api_client.post(
        f"/api/v2/quotes/{quote_id}/accept",
        json=body,
        headers={"Idempotency-Key": key},
    )


# ===========================================================================
# Создание DRAFT
# ===========================================================================
async def test_manager_creates_draft_with_unfrozen_total(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Quote Brand")
    product = await create_product(
        session_factory, sku="V2-QT-1", name="Quote product", brand=brand, base_price=100
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.post(
        "/api/v2/manager/quotes",
        json=_quote_payload(
            organization.id,
            [(product, "2", "15.50", "Спец цена по договорённости")],
            valid_until=None,
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    # У DRAFT номера нет — он присваивается при SEND (этап 8).
    assert body["number"] is None
    assert body["seq"] is None
    # total не заморожен: равен сумме позиций и пересчитывается при правках.
    assert body["total"] == {"amount": "31.00", "currency": "BYN"}
    assert body["items"][0]["unitPrice"] == {"amount": "15.50", "currency": "BYN"}
    assert body["items"][0]["lineTotal"] == {"amount": "31.00", "currency": "BYN"}
    assert body["items"][0]["sku"] == "V2-QT-1"
    assert body["items"][0]["comment"] == "Спец цена по договорённости"
    # S3-ключи и внутренние идентификаторы наружу не утекают.
    assert "s3" not in response.text.lower()
    assert "createdBy" not in response.text

    async with session_factory() as session:
        stored = await session.get(Quote, uuid.UUID(body["id"]))
        assert stored is not None
        assert stored.status == QuoteStatus.DRAFT
        assert str(stored.total_amount) == "31.00"
        assert stored.created_by is not None
        # Аудит quote.create записан (этап 8).
        audits = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "quote",
                    AuditLog.target_id == stored.id,
                    AuditLog.action == "quote.create",
                )
            )
        ).scalars().all()
        assert len(audits) == 1


async def test_create_quote_rejects_unknown_product_and_archived(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Quote Bad Brand")
    archived = await create_product(
        session_factory,
        sku="V2-QT-ARCH",
        name="Archived product",
        brand=brand,
        base_price=10,
        stock="ARCHIVED",
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    # Несуществующий товар → 409 QUOTE_ITEM_UNAVAILABLE.
    missing = await api_client.post(
        "/api/v2/manager/quotes",
        json=_quote_payload(organization.id, [(uuid.uuid4(), "1", "5.00", None)]),
    )
    assert missing.status_code == 409, missing.text
    assert missing.json()["code"] == "QUOTE_ITEM_UNAVAILABLE"

    # Архивный товар → 409 PRODUCT_UNAVAILABLE.
    archived_response = await api_client.post(
        "/api/v2/manager/quotes",
        json=_quote_payload(organization.id, [(archived, "1", "5.00", None)]),
    )
    assert archived_response.status_code == 409, archived_response.text
    assert archived_response.json()["code"] == "PRODUCT_UNAVAILABLE"


# ===========================================================================
# SEND: номер, заморозка, уведомление
# ===========================================================================
async def test_send_requires_valid_until_then_freezes_number_and_total(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Send Brand")
    product = await create_product(
        session_factory, sku="V2-QT-SEND", name="Send product", brand=brand, base_price=100
    )
    client, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    # КП без valid_until: send → 400 QUOTE_VALID_UNTIL_REQUIRED.
    draft = await _create_quote(
        api_client, organization, [(product, "2", "15.50", None)], valid_until=None
    )
    no_deadline = await _send_quote(api_client, draft["id"])
    assert no_deadline.status_code == 400, no_deadline.text
    assert no_deadline.json()["code"] == "QUOTE_VALID_UNTIL_REQUIRED"

    # КП с valid_until в прошлом: send → 400 QUOTE_VALID_UNTIL_IN_PAST.
    past = await _create_quote(
        api_client,
        organization,
        [(product, "2", "15.50", None)],
        valid_until="2020-01-01T00:00:00+00:00",
    )
    expired_send = await _send_quote(api_client, past["id"])
    assert expired_send.status_code == 400, expired_send.text
    assert expired_send.json()["code"] == "QUOTE_VALID_UNTIL_IN_PAST"

    # Корректный send: первый номер сессии — КП-2026-000001, total заморожен.
    draft2 = await _create_quote(
        api_client, organization, [(product, "2", "15.50", None)]
    )
    sent = await _send_quote(api_client, draft2["id"])
    assert sent.status_code == 200, sent.text
    body = sent.json()["data"]
    assert body["status"] == "SENT"
    assert body["version"] == draft2["version"] + 1
    assert body["number"] == "КП-2026-000001"
    assert body["total"] == {"amount": "31.00", "currency": "BYN"}

    # В БД: номер/seq зафиксированы, статус SENT, аудит + NEW_QUOTE клиенту.
    async with session_factory() as session:
        stored = await session.get(Quote, uuid.UUID(body["id"]))
        assert stored.status == QuoteStatus.SENT
        assert stored.number == "КП-2026-000001"
        assert stored.seq == 1
        assert str(stored.total_amount) == "31.00"

        audits = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "quote",
                    AuditLog.target_id == stored.id,
                    AuditLog.action == "quote.send",
                )
            )
        ).scalars().all()
        assert len(audits) == 1

        notifications = (
            await session.execute(
                select(Notification).where(
                    Notification.type == "NEW_QUOTE",
                    Notification.user_id == client.id,
                )
            )
        ).scalars().all()
        assert len(notifications) == 1
        assert "КП-2026-000001" in (notifications[0].body or "")

    # Повторный send по той же версии → 409 (уже не DRAFT).
    again = await _send_quote(api_client, draft2["id"])
    assert again.status_code == 409
    assert again.json()["code"] == "QUOTE_NOT_DRAFT"


# ===========================================================================
# Видимость КП клиентом (org-scope)
# ===========================================================================
async def test_client_sees_own_org_quotes_only_and_drafts_hidden(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Vis Brand")
    product = await create_product(
        session_factory, sku="V2-QT-VIS", name="Vis product", brand=brand, base_price=100
    )
    client, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    sent_quote = await _create_quote(
        api_client, organization, [(product, "1", "42.00", None)]
    )
    sent = await _send_quote(api_client, sent_quote["id"])
    assert sent.status_code == 200, sent.text

    draft_quote = await _create_quote(
        api_client, organization, [(product, "3", "10.00", None)]
    )

    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)

    # Список своей org: SENT виден, DRAFT в клиентской ленте отсутствует.
    listing = await api_client.get("/api/v2/quotes")
    assert listing.status_code == 200, listing.text
    ids = [row["id"] for row in listing.json()["data"]]
    assert sent_quote["id"] in ids
    assert draft_quote["id"] not in ids

    row = next(item for item in listing.json()["data"] if item["id"] == sent_quote["id"])
    assert row["number"] == sent.json()["data"]["number"]
    assert row["status"] == "SENT"

    # Деталь SENT — 200.
    detail = await api_client.get(f"/api/v2/quotes/{sent_quote['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "SENT"

    # DRAFT клиенту не виден — 404 (без утечки существования).
    draft_detail = await api_client.get(f"/api/v2/quotes/{draft_quote['id']}")
    assert draft_detail.status_code == 404
    assert draft_detail.json()["code"] == "QUOTE_NOT_FOUND"

    # Чужая организация → 404.
    outsider, outsider_org = await _seed_client_with_org(
        session_factory, email=OUTSIDER_EMAIL
    )
    await _logout(api_client)
    await _login(api_client, OUTSIDER_EMAIL)
    foreign = await api_client.get(f"/api/v2/quotes/{sent_quote['id']}")
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "QUOTE_NOT_FOUND"
    foreign_list = await api_client.get("/api/v2/quotes")
    assert foreign_list.status_code == 200
    assert foreign_list.json()["data"] == []


# ===========================================================================
# ACCEPT: заявка с ценами КП, идемпотентность, гейт согласования
# ===========================================================================
async def test_accept_creates_order_with_quote_prices_and_replays_same_key(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Accept Brand")
    product = await create_product(
        session_factory, sku="V2-QT-ACC", name="Accept product", brand=brand, base_price=100
    )
    # Режим визы ALL: клиент BUYER (не OWNER) → заявка ждёт визу OWNER.
    client, organization = await _seed_client_with_org(
        session_factory, approval=ApprovalMode.ALL
    )
    await _login(api_client, MANAGER_EMAIL)
    quote = await _create_quote(
        api_client,
        organization,
        [(product, "2", "77.50", "Комментарий позиции КП")],
    )
    sent = await _send_quote(api_client, quote["id"])
    assert sent.status_code == 200, sent.text
    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)

    response = await _accept(api_client, quote["id"], key="acc-key-1")

    assert response.status_code == 201, response.text
    order = response.json()["data"]
    assert order["status"] == "NEW"
    # Гейт согласования по настройкам org (ALL + создатель не OWNER → PENDING).
    assert order["approvalStatus"] == "PENDING"
    # Цены ИЗ КП: override 77.50, а НЕ базовая цена товара 100.00.
    assert order["total"] == {"amount": "155.00", "currency": "BYN"}
    line = order["lines"][0]
    assert line["unitPrice"] == {"amount": "77.50", "currency": "BYN"}
    assert line["quantity"] == 2
    assert line["note"] == "Комментарий позиции КП"
    assert response.headers["X-Idempotency-Replayed"] == "false"

    # В БД: позиции и сумма заказа равны КП, статус КП ACCEPTED, виза PENDING.
    async with session_factory() as session:
        stored_quote = await session.get(Quote, uuid.UUID(quote["id"]))
        assert stored_quote.status == QuoteStatus.ACCEPTED
        assert stored_quote.version == sent.json()["data"]["version"] + 1

        stored_order = await session.get(Order, uuid.UUID(order["id"]))
        assert stored_order.total_amount == stored_quote.total_amount
        assert stored_order.approval_status is ApprovalStatus.PENDING
        assert stored_order.currency_code == "BYN"

        items = (
            await session.execute(
                select(OrderItem).where(OrderItem.order_id == stored_order.id)
            )
        ).scalars().all()
        assert len(items) == 1
        assert str(items[0].unit_price) == "77.50"
        assert items[0].note == "Комментарий позиции КП"
        assert items[0].product_snapshot["sku"] == "V2-QT-ACC"

        # Уведомление менеджеру-создателю (QUOTE_ACCEPTED).
        notifs = (
            await session.execute(
                select(Notification).where(Notification.type == "QUOTE_ACCEPTED")
            )
        ).scalars().all()
        assert len(notifs) == 1
        assert notifs[0].user_id == stored_quote.created_by

    # Повторный accept с тем же ключом и тем же телом → replay той же заявки.
    replay = await _accept(api_client, quote["id"], key="acc-key-1")
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["id"] == order["id"]
    assert replay.headers["X-Idempotency-Replayed"] == "true"

    # Тот же ключ с другим телом (другой комментарий доставки) → KEY_REUSED.
    reused = await _accept(
        api_client,
        quote["id"],
        key="acc-key-1",
        delivery={"delivery": {"method": "DELIVERY", "contactName": "Другой"}},
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    # Второй accept с НОВЫМ ключом → КП уже ACCEPTED → 409 QUOTE_STATE_CHANGED.
    second = await _accept(api_client, quote["id"], key="acc-key-2")
    assert second.status_code == 409, second.text
    assert second.headers["content-type"].startswith("application/problem+json")
    assert second.json()["code"] == "QUOTE_STATE_CHANGED"


async def test_accept_expired_quote_is_409(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Expired Brand")
    product = await create_product(
        session_factory, sku="V2-QT-EXP", name="Expired product", brand=brand, base_price=100
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    quote = await _create_quote(
        api_client, organization, [(product, "1", "50.00", None)]
    )
    sent = await _send_quote(api_client, quote["id"])
    assert sent.status_code == 200, sent.text

    # valid_until в прошлом — правим БД напрямую (beat ещё не успел).
    async with session_factory() as session:
        stored = await session.get(Quote, uuid.UUID(quote["id"]))
        stored.valid_until = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await session.commit()
    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)

    response = await _accept(api_client, quote["id"], key="acc-expired")

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "QUOTE_EXPIRED"

    # После неудачного accept КП помечено EXPIRED (ленивое истечение закоммичено
    # роутером детали/accept... здесь accept откатился — проверяем через чтение).
    detail = await api_client.get(f"/api/v2/quotes/{quote['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "EXPIRED"


async def test_reject_then_accept_conflicts(api_client, session_factory):
    manager = await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Reject Brand")
    product = await create_product(
        session_factory, sku="V2-QT-RJT", name="Reject product", brand=brand, base_price=100
    )
    client, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    quote = await _create_quote(
        api_client, organization, [(product, "1", "50.00", None)]
    )
    sent = await _send_quote(api_client, quote["id"])
    assert sent.status_code == 200, sent.text
    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)

    rejected = await api_client.post(f"/api/v2/quotes/{quote['id']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "REJECTED"

    async with session_factory() as session:
        stored = await session.get(Quote, uuid.UUID(quote["id"]))
        assert stored.status == QuoteStatus.REJECTED
        assert stored.version == sent.json()["data"]["version"] + 1

        notifs = (
            await session.execute(
                select(Notification).where(Notification.type == "QUOTE_REJECTED")
            )
        ).scalars().all()
        assert len(notifs) == 1
        assert notifs[0].user_id == manager.id

    # accept после reject → 409 (решение по КП уже принято).
    response = await _accept(api_client, quote["id"], key="acc-rejected")
    assert response.status_code == 409
    assert response.json()["code"] == "QUOTE_STATE_CHANGED"


# ===========================================================================
# RBAC
# ===========================================================================
async def test_rbac_client_blocked_on_manager_routes_anon_on_client_routes(
    api_client, session_factory
):
    _, _ = await _seed_client_with_org(session_factory)
    await _login(api_client, CLIENT_EMAIL)

    # Клиент на менеджерских маршрутах → 403.
    manager_list = await api_client.get("/api/v2/manager/quotes")
    assert manager_list.status_code == 403
    assert manager_list.json()["code"] == "PERMISSION_DENIED"

    manager_create = await api_client.post(
        "/api/v2/manager/quotes",
        json={"organizationId": str(uuid.uuid4()), "items": []},
    )
    assert manager_create.status_code == 403

    await _logout(api_client)

    # Аноним на клиентских маршрутах → 401.
    anon_list = await api_client.get("/api/v2/quotes")
    assert anon_list.status_code == 401
    anon_detail = await api_client.get(f"/api/v2/quotes/{uuid.uuid4()}")
    assert anon_detail.status_code == 401
    anon_accept = await _accept(api_client, str(uuid.uuid4()), key="anon-key")
    assert anon_accept.status_code == 401


# ===========================================================================
# PDF: синхронный рендер + скачивание байтами
# ===========================================================================
async def test_manager_renders_pdf_sync_and_client_downloads_bytes(
    api_client, session_factory, pdf_mock
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Pdf Brand")
    product = await create_product(
        session_factory, sku="V2-QT-PDF", name="Pdf product", brand=brand, base_price=100
    )
    client, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    quote = await _create_quote(
        api_client, organization, [(product, "2", "19.99", None)]
    )
    sent = await _send_quote(api_client, quote["id"])
    assert sent.status_code == 200, sent.text
    number = sent.json()["data"]["number"]

    render = await api_client.post(f"/api/v2/manager/quotes/{quote['id']}/pdf")

    assert render.status_code == 200, render.text
    body = render.json()["data"]
    assert body["pdfStatus"] == "READY"
    assert body["pdfFileAssetId"] is not None
    # Файл ушёл в бакет PDF-каталогов под ключ quotes/quote-{seq}.pdf.
    assert pdf_mock["uploads"], "storage.upload_fileobj не вызван"
    upload = pdf_mock["uploads"][0]
    expected_seq = sent.json()["data"]["seq"]
    assert upload["key"] == f"quotes/quote-{expected_seq}.pdf"

    # В БД: pdf_status=READY, FileAsset(type=QUOTE_PDF, visibility=AUTHED).
    from app.models.enums import FileAssetType, FileVisibility
    from app.models.file import FileAsset

    async with session_factory() as session:
        stored = await session.get(Quote, uuid.UUID(quote["id"]))
        assert stored.pdf_status == QuotePdfStatus.READY
        asset = await session.get(FileAsset, stored.pdf_file_asset_id)
        assert asset is not None
        assert asset.type == FileAssetType.QUOTE_PDF
        assert asset.visibility == FileVisibility.AUTHED
        assert asset.filename_display == f"{number}.pdf"

    # Клиент скачивает байтами (org-scope, attachment, %PDF-магия).
    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)
    download = await api_client.get(f"/api/v2/quotes/{quote['id']}/pdf/download")
    assert download.status_code == 200, download.text
    assert download.content.startswith(b"%PDF")
    assert download.headers["content-type"] == "application/pdf"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition

    # Чужой клиент — 404 и на деталь, и на скачивание.
    await _seed_client_with_org(session_factory, email=OUTSIDER_EMAIL)
    await _logout(api_client)
    await _login(api_client, OUTSIDER_EMAIL)
    foreign_download = await api_client.get(
        f"/api/v2/quotes/{quote['id']}/pdf/download"
    )
    assert foreign_download.status_code == 404
    assert foreign_download.json()["code"] == "QUOTE_NOT_FOUND"


async def test_render_pdf_for_draft_conflicts(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Pdf Draft Brand")
    product = await create_product(
        session_factory, sku="V2-QT-PDFD", name="Pdf draft product", brand=brand, base_price=100
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    draft = await _create_quote(
        api_client, organization, [(product, "1", "5.00", None)]
    )

    response = await api_client.post(f"/api/v2/manager/quotes/{draft['id']}/pdf")

    # PDF-ключ строится по seq — у DRAFT номера нет → 409.
    assert response.status_code == 409
    assert response.json()["code"] == "QUOTE_NOT_SENT"


# ===========================================================================
# PATCH / DELETE: DRAFT-only, optimistic concurrency
# ===========================================================================
async def test_patch_draft_updates_items_bumps_version_and_rejects_stale(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Patch Brand")
    product_a = await create_product(
        session_factory, sku="V2-QT-PA", name="Product A", brand=brand, base_price=10
    )
    product_b = await create_product(
        session_factory, sku="V2-QT-PB", name="Product B", brand=brand, base_price=20
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    draft = await _create_quote(
        api_client, organization, [(product_a, "1", "5.00", None)]
    )

    response = await api_client.patch(
        f"/api/v2/manager/quotes/{draft['id']}",
        json={
            "items": [
                {
                    "productId": str(product_b.id),
                    "quantity": "3",
                    "unitPrice": {"amount": "7.25", "currency": "BYN"},
                }
            ]
        },
        headers={"If-Match": str(draft["version"])},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["version"] == draft["version"] + 1
    # total не заморожен в DRAFT — пересчитан по новым позициям.
    assert body["total"] == {"amount": "21.75", "currency": "BYN"}
    assert body["items"][0]["sku"] == "V2-QT-PB"

    # Повтор с той же версией теперь устарел → 409 STALE_RESOURCE_VERSION.
    stale = await api_client.patch(
        f"/api/v2/manager/quotes/{draft['id']}",
        json={
            "items": [
                {
                    "productId": str(product_a.id),
                    "quantity": "1",
                    "unitPrice": {"amount": "5.00", "currency": "BYN"},
                }
            ]
        },
        headers={"If-Match": str(draft["version"])},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"

    # PATCH без If-Match → 400 INVALID_IF_MATCH.
    missing = await api_client.patch(
        f"/api/v2/manager/quotes/{draft['id']}",
        json={"items": []},
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "INVALID_IF_MATCH"


async def test_patch_and_delete_sent_quote_conflict_and_delete_draft(
    api_client, session_factory
):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Del Brand")
    product = await create_product(
        session_factory, sku="V2-QT-DEL", name="Del product", brand=brand, base_price=10
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    sent_quote = await _create_quote(
        api_client, organization, [(product, "1", "5.00", None)]
    )
    sent = await _send_quote(api_client, sent_quote["id"])
    assert sent.status_code == 200, sent.text
    sent_version = sent.json()["data"]["version"]

    # PATCH SENT → 409 QUOTE_NOT_DRAFT.
    patch_sent = await api_client.patch(
        f"/api/v2/manager/quotes/{sent_quote['id']}",
        json={
            "items": [
                {
                    "productId": str(product.id),
                    "quantity": "2",
                    "unitPrice": {"amount": "5.00", "currency": "BYN"},
                }
            ]
        },
        headers={"If-Match": str(sent_version)},
    )
    assert patch_sent.status_code == 409
    assert patch_sent.json()["code"] == "QUOTE_NOT_DRAFT"

    # DELETE SENT → 409 QUOTE_NOT_DRAFT.
    delete_sent = await api_client.delete(f"/api/v2/manager/quotes/{sent_quote['id']}")
    assert delete_sent.status_code == 409
    assert delete_sent.json()["code"] == "QUOTE_NOT_DRAFT"

    # DELETE DRAFT → 204, позиции удалены каскадом.
    draft = await _create_quote(
        api_client, organization, [(product, "1", "5.00", None)]
    )
    deleted = await api_client.delete(f"/api/v2/manager/quotes/{draft['id']}")
    assert deleted.status_code == 204, deleted.text

    from app.models.quote import QuoteItem

    async with session_factory() as session:
        gone = await session.get(Quote, uuid.UUID(draft["id"]))
        assert gone is None
        items = (
            await session.execute(
                select(QuoteItem).where(QuoteItem.quote_id == uuid.UUID(draft["id"]))
            )
        ).scalars().all()
        assert items == []


# ===========================================================================
# Менеджерская коллекция: курсор и фильтр статуса
# ===========================================================================
async def test_manager_list_filters_by_status_and_paginates(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="List Brand")
    product = await create_product(
        session_factory, sku="V2-QT-LIST", name="List product", brand=brand, base_price=10
    )
    _, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    sent_quote = await _create_quote(
        api_client, organization, [(product, "1", "5.00", None)]
    )
    await _send_quote(api_client, sent_quote["id"])
    draft_quote = await _create_quote(
        api_client, organization, [(product, "2", "6.00", None)]
    )

    listed = await api_client.get("/api/v2/manager/quotes")
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert len(page["data"]) == 2
    assert page["meta"]["hasMore"] is False
    assert page["meta"]["sort"] == "createdAt,id"

    filtered = await api_client.get("/api/v2/manager/quotes?status=SENT")
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()["data"]] == [sent_quote["id"]]

    # Курсорная страница: limit=1 → hasMore=true и валидный next_cursor.
    first_page = await api_client.get("/api/v2/manager/quotes?limit=1")
    assert first_page.status_code == 200
    assert first_page.json()["meta"]["hasMore"] is True
    next_cursor = first_page.json()["meta"]["nextCursor"]
    assert next_cursor is not None
    second_page = await api_client.get(
        f"/api/v2/manager/quotes?limit=1&cursor={next_cursor}"
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["data"]) == 1

    # Подделанный курсор → 422 VALIDATION_ERROR.
    forged = await api_client.get(
        "/api/v2/manager/quotes?limit=1&cursor=garbage.garbage"
    )
    assert forged.status_code == 422


# ===========================================================================
# Идемпотентность accept: IN_PROGRESS (ключ забронирован, order_id нет)
# ===========================================================================
async def test_accept_in_flight_returns_in_progress_code(api_client, session_factory):
    from app.models.order import OrderIdempotency
    from app.services.quote import quote_accept_fingerprint
    from app.schemas.v2.orders import OrderDeliveryCreate

    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="InFlight Brand")
    product = await create_product(
        session_factory, sku="V2-QT-INFL", name="InFlight product", brand=brand, base_price=100
    )
    client, organization = await _seed_client_with_org(session_factory)
    await _login(api_client, MANAGER_EMAIL)
    quote = await _create_quote(
        api_client, organization, [(product, "1", "50.00", None)]
    )
    sent = await _send_quote(api_client, quote["id"])
    assert sent.status_code == 200, sent.text
    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)

    # Точно тот же delivery, что пошлёт _accept ниже — иначе fingerprint
    # разойдётся и тест увидит IDEMPOTENCY_KEY_REUSED вместо IN_PROGRESS.
    delivery = OrderDeliveryCreate(
        method="PICKUP", contact_name="Иван", phone="+375291234567"
    )
    request_hash = quote_accept_fingerprint(
        user_id=client.id, quote_id=uuid.UUID(quote["id"]), delivery=delivery
    )
    async with session_factory() as session:
        session.add(
            OrderIdempotency(
                user_id=client.id,
                idempotency_key="acc-inflight",
                request_hash=request_hash,
            )
        )
        await session.commit()

    response = await _accept(api_client, quote["id"], key="acc-inflight")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
