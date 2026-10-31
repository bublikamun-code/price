"""Согласование заявок в организации (этап 6 роадмапа, §16 п.42).

Покрывает: гейт при создании (OVER_LIMIT с строгой границей «равно», ALL),
визу OWNER (approve/reject, идемпотентность состоянием), блокировки FSM
(PENDING не обрабатывается менеджером, REJECTED терминален), отмену PENDING,
настройки PATCH /organizations/{id}/approval и уведомления
ORDER_APPROVAL_REQUESTED / ORDER_APPROVED / ORDER_REJECTED (§20.3).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.catalog import Product
from app.models.enums import (
    ApprovalMode,
    ApprovalStatus,
    OrderStatus,
    OrganizationRole,
    UserRole,
)
from app.models.order import Order
from app.models.organization import Organization
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
OWNER_EMAIL = "v2-approval-owner@example.by"
BUYER_EMAIL = "v2-approval-buyer@example.by"
OUTSIDER_EMAIL = "v2-approval-outsider@example.by"
MANAGER_EMAIL = "v2-approval-manager@example.by"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _seed_users(session_factory, *, owner: bool = True):
    """CLIENT-покупатель + OWNER той же организации (+ активная организация)."""
    buyer = await create_user(
        session_factory, email=BUYER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(
        session_factory, legal_name="Approval Org"
    )
    await add_organization_membership(
        session_factory,
        user=buyer,
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    owner_user = None
    if owner:
        owner_user = await create_user(
            session_factory, email=OWNER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
        )
        await add_organization_membership(
            session_factory,
            user=owner_user,
            organization=organization,
            role=OrganizationRole.OWNER,
            is_primary=True,
        )
    await set_active_organization(
        session_factory, user=buyer, organization=organization
    )
    return organization, (buyer, owner_user)


def _payload(product: Product, quantity: str = "3") -> dict:
    return {
        "draftId": None,
        "items": [
            {"productId": str(product.id), "quantity": quantity, "note": None}
        ],
        "delivery": {
            "method": "PICKUP",
            "contactName": None,
            "phone": None,
            "preferredDate": None,
            "comment": None,
        },
    }


async def _create_order(api_client, product: Product, quantity: str = "3"):
    response = await api_client.post(
        "/api/v2/orders",
        json=_payload(product, quantity),
        headers={"Idempotency-Key": f"v2-approval-{uuid.uuid4()}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _seed_order(
    session_factory,
    *,
    client,
    product,
    organization,
    approval_status: ApprovalStatus = ApprovalStatus.PENDING,
) -> Order:
    """Прямой сид заявки в нужном approval-состоянии (виза/гварды)."""
    async with session_factory() as session:
        order = Order(
            client_id=client.id,
            organization_id=organization.id,
            status=OrderStatus.NEW,
            approval_status=approval_status,
            currency_code="BYN",
            exchange_rate="1.0000",
            rate_source="BYN",
            total_amount="300.00",
            delivery_method="pickup",
            delivery_point="Минск",
            created_at=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc),
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def _notifications(session_factory, *, type: str) -> list[Notification]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(Notification).where(Notification.type == type)
        )
        return list(rows)


# ---------- Гейт при создании (§16 п.42 п.1-3) -------------------------------


async def test_over_limit_equal_total_passes_without_visa(api_client, session_factory):
    """Граница OVER_LIMIT строгая: total == limit → NOT_REQUIRED (§16 п.42 п.2)."""
    organization, (_buyer, _owner) = await _seed_users(session_factory)
    await set_organization_approval(
        session_factory, organization=organization, mode=ApprovalMode.OVER_LIMIT,
        limit="300.00",
    )
    brand = await create_brand(session_factory, name="Approval Brand 1")
    product = await create_product(
        session_factory, sku="V2-APPR-1", name="Boundary product",
        brand=brand, base_price=100, stock_qty=10,
    )
    await _login(api_client, BUYER_EMAIL)

    data = await _create_order(api_client, product, quantity="3")

    assert data["approvalStatus"] == "NOT_REQUIRED"
    assert data["total"] == {"amount": "300.00", "currency": "BYN"}
    assert data["approvedBy"] is None and data["rejectionReason"] is None


async def test_over_limit_creates_pending_and_notifies_owners(
    api_client, session_factory
):
    """total > limit у создателя-не-OWNER → PENDING + виза-запрос OWNER'ам."""
    organization, (_buyer, owner) = await _seed_users(session_factory)
    await set_organization_approval(
        session_factory, organization=organization, mode=ApprovalMode.OVER_LIMIT,
        limit="299.99",
    )
    brand = await create_brand(session_factory, name="Approval Brand 2")
    product = await create_product(
        session_factory, sku="V2-APPR-2", name="Over-limit product",
        brand=brand, base_price=100, stock_qty=10,
    )
    await _login(api_client, BUYER_EMAIL)

    data = await _create_order(api_client, product, quantity="3")

    assert data["approvalStatus"] == "PENDING"
    async with session_factory() as session:
        stored = await session.get(Order, uuid.UUID(data["id"]))
        assert stored.approval_status is ApprovalStatus.PENDING
    requested = await _notifications(
        session_factory, type="ORDER_APPROVAL_REQUESTED"
    )
    assert [str(n.user_id) for n in requested] == [str(owner.id)]
    assert requested[0].payload["order_id"] == data["id"]
    # NEW_ORDER менеджерам сохраняется без изменений (§16 п.42 п.8).
    assert await _notifications(session_factory, type="NEW_ORDER")


async def test_all_mode_owner_creator_skips_visa(api_client, session_factory):
    """Создатель-OWNER визы не требует даже при ALL (§16 п.42 п.3)."""
    organization, (_buyer, owner) = await _seed_users(session_factory)
    await set_organization_approval(
        session_factory, organization=organization, mode=ApprovalMode.ALL
    )
    brand = await create_brand(session_factory, name="Approval Brand 3")
    product = await create_product(
        session_factory, sku="V2-APPR-3", name="Owner product",
        brand=brand, base_price=100, stock_qty=10,
    )
    await set_active_organization(
        session_factory, user=owner, organization=organization
    )
    await _login(api_client, OWNER_EMAIL)

    data = await _create_order(api_client, product, quantity="3")

    assert data["approvalStatus"] == "NOT_REQUIRED"


async def test_all_mode_buyer_creator_requires_visa(api_client, session_factory):
    """ALL + создатель-BUYER → PENDING."""
    organization, (_buyer, _owner) = await _seed_users(session_factory)
    await set_organization_approval(
        session_factory, organization=organization, mode=ApprovalMode.ALL
    )
    brand = await create_brand(session_factory, name="Approval Brand 4")
    product = await create_product(
        session_factory, sku="V2-APPR-4", name="Buyer product",
        brand=brand, base_price=100, stock_qty=10,
    )
    await _login(api_client, BUYER_EMAIL)

    data = await _create_order(api_client, product, quantity="3")

    assert data["approvalStatus"] == "PENDING"


# ---------- Виза OWNER (§16 п.42 п.6) ---------------------------------------


async def test_approve_requires_owner_role_and_membership(api_client, session_factory):
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 5")
    product = await create_product(
        session_factory, sku="V2-APPR-5", name="Guard product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )

    await _login(api_client, BUYER_EMAIL)
    buyer_response = await api_client.post(f"/api/v2/orders/{order.id}/approve")

    assert buyer_response.status_code == 403, buyer_response.text
    assert buyer_response.json()["code"] == "PERMISSION_DENIED"

    await create_user(
        session_factory, email=OUTSIDER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await _login(api_client, OUTSIDER_EMAIL)
    outsider_response = await api_client.post(f"/api/v2/orders/{order.id}/approve")

    assert outsider_response.status_code == 404
    assert outsider_response.json()["code"] == "ORDER_NOT_FOUND"


async def test_owner_approve_sets_state_and_replays_as_noop(
    api_client, session_factory
):
    organization, (buyer, owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 6")
    product = await create_product(
        session_factory, sku="V2-APPR-6", name="Visa product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )
    await _login(api_client, OWNER_EMAIL)

    response = await api_client.post(f"/api/v2/orders/{order.id}/approve")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["approvalStatus"] == "APPROVED"
    assert data["approvedBy"] == str(owner.id)
    assert data["approvedAt"] is not None
    assert data["rejectionReason"] is None
    assert data["version"] == order.version + 1
    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "order.approve", AuditLog.target_id == order.id
            )
        )
        assert audit is not None and audit.actor_id == owner.id

    replay = await api_client.post(f"/api/v2/orders/{order.id}/approve")

    # Идемпотентность машинным состоянием: 200 no-op, version не растёт.
    assert replay.status_code == 200
    assert replay.json()["data"]["version"] == data["version"]
    approved = await _notifications(session_factory, type="ORDER_APPROVED")
    assert [str(n.user_id) for n in approved] == [str(buyer.id)]


async def test_reject_after_approve_conflicts(api_client, session_factory):
    """Обратная виза не переписывает решение: reject из APPROVED → 409 (§6)."""
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 8")
    product = await create_product(
        session_factory, sku="V2-APPR-8", name="Visa product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )
    await _login(api_client, OWNER_EMAIL)
    await api_client.post(f"/api/v2/orders/{order.id}/approve")

    response = await api_client.post(
        f"/api/v2/orders/{order.id}/reject", json={"reason": "передумали"}
    )

    assert response.status_code == 409, response.text
    assert response.headers.get("x-error-code") == "APPROVAL_NOT_PENDING"
    async with session_factory() as session:
        refreshed = await session.get(Order, order.id)
        assert refreshed is not None
        assert refreshed.approval_status is ApprovalStatus.APPROVED
        assert refreshed.rejection_reason is None


async def test_owner_reject_records_reason_and_requires_it(
    api_client, session_factory
):
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 7")
    product = await create_product(
        session_factory, sku="V2-APPR-7", name="Reject product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )
    await _login(api_client, OWNER_EMAIL)

    missing_reason = await api_client.post(f"/api/v2/orders/{order.id}/reject", json={})
    assert missing_reason.status_code == 422

    response = await api_client.post(
        f"/api/v2/orders/{order.id}/reject",
        json={"reason": "Нет бюджета на этот квартал"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["approvalStatus"] == "REJECTED"
    assert data["rejectionReason"] == "Нет бюджета на этот квартал"
    assert data["approvedAt"] is not None
    rejected = await _notifications(session_factory, type="ORDER_REJECTED")
    assert [str(n.user_id) for n in rejected] == [str(buyer.id)]
    assert "Нет бюджета" in rejected[0].body


async def test_approve_not_required_order_conflicts(api_client, session_factory):
    """Виза принимается только из PENDING: NOT_REQUIRED → 409 (§16 п.42 п.6)."""
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 8")
    product = await create_product(
        session_factory, sku="V2-APPR-8", name="Plain product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory,
        client=buyer,
        product=product,
        organization=organization,
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    await _login(api_client, OWNER_EMAIL)

    response = await api_client.post(f"/api/v2/orders/{order.id}/approve")

    assert response.status_code == 409
    assert response.json()["code"] == "APPROVAL_NOT_PENDING"


# ---------- Блокировки FSM и отмена (§16 п.42 п.5) --------------------------


async def test_manager_cannot_process_pending_until_approved(
    api_client, session_factory
):
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 9")
    product = await create_product(
        session_factory, sku="V2-APPR-9", name="FSM product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    await _login(api_client, MANAGER_EMAIL)

    pending = await api_client.patch(
        f"/api/v1/manager/orders/{order.id}", json={"status": "IN_PROGRESS"}
    )
    assert pending.status_code == 409
    assert pending.headers["X-Error-Code"] == "APPROVAL_PENDING"

    # Виза выдана → обычный FSM проходит.
    await _login(api_client, OWNER_EMAIL)
    approved = await api_client.post(f"/api/v2/orders/{order.id}/approve")
    assert approved.status_code == 200

    await _login(api_client, MANAGER_EMAIL)
    processed = await api_client.patch(
        f"/api/v1/manager/orders/{order.id}", json={"status": "IN_PROGRESS"}
    )
    assert processed.status_code == 200, processed.text
    assert processed.json()["status"] == "IN_PROGRESS"


async def test_cancel_pending_allowed_rejected_terminal(api_client, session_factory):
    organization, (buyer, _owner) = await _seed_users(session_factory)
    brand = await create_brand(session_factory, name="Approval Brand 10")
    product = await create_product(
        session_factory, sku="V2-APPR-10", name="Cancel product", brand=brand, base_price=10
    )
    pending_order = await _seed_order(
        session_factory, client=buyer, product=product, organization=organization
    )
    await _login(api_client, BUYER_EMAIL)

    cancelled = await api_client.post(f"/api/v2/orders/{pending_order.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "CANCELLED"

    rejected_order = await _seed_order(
        session_factory,
        client=buyer,
        product=product,
        organization=organization,
        approval_status=ApprovalStatus.REJECTED,
    )
    denied = await api_client.post(f"/api/v2/orders/{rejected_order.id}/cancel")

    assert denied.status_code == 409
    assert denied.json()["code"] == "APPROVAL_TERMINAL"


# ---------- Настройки PATCH /organizations/{id}/approval (§16 п.42 п.1) -----


async def test_over_limit_requires_positive_limit(api_client, session_factory):
    organization, (_buyer, _owner) = await _seed_users(session_factory)
    await _login(api_client, OWNER_EMAIL)

    missing = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/approval",
        json={"approvalMode": "OVER_LIMIT"},
    )
    zero = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/approval",
        json={"approvalMode": "OVER_LIMIT", "approvalLimitAmount": 0},
    )

    assert missing.status_code == 422, missing.text
    assert zero.status_code == 422


async def test_owner_updates_settings_and_detail_exposes_fields(
    api_client, session_factory
):
    organization, (_buyer, _owner) = await _seed_users(session_factory)
    await _login(api_client, OWNER_EMAIL)

    response = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/approval",
        json={"approvalMode": "OVER_LIMIT", "approvalLimitAmount": "250.50"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["approvalMode"] == "OVER_LIMIT"
    assert data["approvalLimitAmount"] == "250.50"
    # Ответ PATCH — та же форма organizationDetail, что GET (координация с фронтом).
    async with session_factory() as session:
        stored = await session.get(Organization, organization.id)
        assert stored.approval_mode is ApprovalMode.OVER_LIMIT
        assert stored.approval_limit_amount == Decimal("250.50")


async def test_buyer_cannot_update_approval_settings(api_client, session_factory):
    organization, (_buyer, _owner) = await _seed_users(session_factory)
    await _login(api_client, BUYER_EMAIL)

    response = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/approval",
        json={"approvalMode": "ALL"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PERMISSION_DENIED"
