"""Organization expand-contract invariants and legacy compatibility."""
from decimal import Decimal

import pytest

from app.models.enums import OrganizationRole, StockStatus, UserRole
from app.models.user import User
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order import OrderNotFoundError, OrderService, order_request_fingerprint
from app.services.organizations import OrganizationContextService
from app.services.pricing import PricingService
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
    set_organization_brand_term,
    set_organization_pricing_agreement,
    set_rate,
)

pytestmark = pytest.mark.asyncio


async def _order_payload(sku: str) -> OrderCreate:
    return OrderCreate(
        items=[OrderItemCreate(sku=sku, quantity=1)],
        delivery_method="pickup",
        delivery_point="Склад",
    )


async def test_same_company_does_not_create_membership(session_factory):
    first = await create_user(
        session_factory, email="first@company.example", role=UserRole.CLIENT
    )
    second = await create_user(
        session_factory, email="second@company.example", role=UserRole.CLIENT
    )
    async with session_factory() as db:
        for user in (first, second):
            db_user = await db.get(User, user.id)
            db_user.company = "Одинаковая компания"
        await db.commit()

    async with session_factory() as db:
        first_context = await OrganizationContextService(db).resolve(first)
        second_context = await OrganizationContextService(db).resolve(second)

    assert first_context.organization_id is None
    assert second_context.organization_id is None
    assert first_context.memberships == ()
    assert second_context.memberships == ()


async def test_membership_context_requires_explicit_active_organization(session_factory):
    user = await create_user(
        session_factory, email="member@company.example", role=UserRole.CLIENT
    )
    active_org = await create_organization(session_factory, legal_name="Active Org")
    suspended_org = await create_organization(session_factory, legal_name="Suspended Org")
    await add_organization_membership(
        session_factory,
        user=user,
        organization=active_org,
        role=OrganizationRole.OWNER,
        is_primary=True,
    )
    await add_organization_membership(
        session_factory,
        user=user,
        organization=suspended_org,
        is_active=False,
    )

    async with session_factory() as db:
        user.active_organization_id = suspended_org.id
        db.add(user)
        await db.commit()
        await db.refresh(user)
        context = await OrganizationContextService(db).resolve(user)

    assert context.organization_id is None
    assert {m.organization_id for m in context.memberships} == {
        active_org.id,
        suspended_org.id,
    }

    await set_active_organization(
        session_factory, user=user, organization=active_org
    )
    async with session_factory() as db:
        refreshed_user = await db.get(User, user.id)
        selected = await OrganizationContextService(db).resolve(refreshed_user)

    assert selected.organization_id == active_org.id
    assert selected.is_organization_scope is True


async def test_organization_pricing_isolated_and_does_not_use_user_brand(
    session_factory,
):
    user = await create_user(
        session_factory, email="pricing@company.example", role=UserRole.CLIENT
    )
    brand = await create_brand(session_factory, name="Pricing Brand")
    product = await create_product(
        session_factory,
        sku="PRICE-1",
        name="Pricing Product",
        brand=brand,
        base_price=100,
    )
    first_org = await create_organization(session_factory, legal_name="Org One")
    second_org = await create_organization(session_factory, legal_name="Org Two")
    await set_organization_brand_term(
        session_factory, organization=first_org, brand=brand, percent=20
    )
    await set_organization_brand_term(
        session_factory, organization=second_org, brand=brand, percent=5
    )

    from app.models.pricing import UserBrand

    async with session_factory() as db:
        db.add(UserBrand(user_id=user.id, brand_id=brand.id, discount_percent=50))
        await db.commit()
        db_user = await db.get(User, user.id)
        service = PricingService(db)
        first_price = await service.price_product(
            product, db_user, "fixed", organization_id=first_org.id
        )
        second_price = await service.price_product(
            product, db_user, "fixed", organization_id=second_org.id
        )
        missing_term_org = await create_organization(
            session_factory, legal_name="No Terms Org"
        )
        missing_term_price = await service.price_product(
            product, db_user, "fixed", organization_id=missing_term_org.id
        )
        legacy_price = await service.price_product(product, db_user, "fixed")

    assert Decimal(str(first_price["client_price"])) == Decimal("80.00")
    assert Decimal(str(second_price["client_price"])) == Decimal("95.00")
    assert Decimal(str(missing_term_price["client_price"])) == Decimal("100.00")
    assert Decimal(str(legacy_price["client_price"])) == Decimal("50.00")


async def test_organization_rate_and_legacy_user_rate_are_separate(session_factory):
    user = await create_user(
        session_factory, email="rate@company.example", role=UserRole.CLIENT
    )
    organization = await create_organization(
        session_factory, legal_name="Rate Org", default_currency="USD"
    )
    organization_rate = await set_rate(
        session_factory, currency="USD", rate=Decimal("3.00"), scale=1
    )
    user_rate = await set_rate(
        session_factory, currency="RUB", rate=Decimal("30.00"), scale=10
    )
    async with session_factory() as db:
        db_user = await db.get(User, user.id)
        db_user.display_currency = "RUB"
        db_user.fixed_rate_id = user_rate.id
        await db.commit()
        await db.refresh(db_user)
        await set_organization_pricing_agreement(
            session_factory,
            organization=organization,
            display_currency="USD",
            fixed_rate_id=organization_rate.id,
        )
        service = PricingService(db)
        org_resolved = await service.resolve_rate(
            db_user, "fixed", organization_id=organization.id
        )
        legacy_resolved = await service.resolve_rate(db_user, "fixed")

    assert (org_resolved.currency, org_resolved.source) == ("USD", "FIXED")
    assert org_resolved.rate == Decimal("3.00")
    assert (legacy_resolved.currency, legacy_resolved.source) == ("RUB", "FIXED")
    assert legacy_resolved.rate == Decimal("30.00")


async def test_order_uses_validated_membership_and_keeps_initiator(session_factory):
    owner = await create_user(
        session_factory, email="owner@company.example", role=UserRole.CLIENT
    )
    member = await create_user(
        session_factory, email="member@company.example", role=UserRole.CLIENT
    )
    outsider = await create_user(
        session_factory, email="outsider@company.example", role=UserRole.CLIENT
    )
    organization = await create_organization(session_factory, legal_name="Order Org")
    await add_organization_membership(
        session_factory, user=owner, organization=organization, role=OrganizationRole.OWNER
    )
    await add_organization_membership(
        session_factory, user=member, organization=organization
    )
    await set_active_organization(
        session_factory, user=owner, organization=organization
    )
    product = await create_product(
        session_factory,
        sku="ORG-ORDER-1",
        name="Organization order product",
        stock=StockStatus.IN_STOCK,
        stock_qty=10,
    )

    async with session_factory() as db:
        db_owner = await db.get(User, owner.id)
        service = OrderService(db)
        order = await service.create(db_owner, await _order_payload(product.sku))
        await db.commit()
        assert order.organization_id == organization.id
        assert order.client_id == owner.id
        assert await service.get(db_owner, order.id, as_manager=False)

    async with session_factory() as db:
        db_member = await db.get(User, member.id)
        db_outsider = await db.get(User, outsider.id)
        service = OrderService(db)
        assert await service.get(db_member, order.id, as_manager=False)
        with pytest.raises(OrderNotFoundError):
            await service.get(db_outsider, order.id, as_manager=False)


async def test_legacy_order_remains_available_to_its_client(session_factory):
    user = await create_user(
        session_factory, email="legacy@example.by", role=UserRole.CLIENT
    )
    other = await create_user(
        session_factory, email="other@example.by", role=UserRole.CLIENT
    )
    product = await create_product(
        session_factory,
        sku="LEGACY-ORDER-1",
        name="Legacy order product",
        stock=StockStatus.IN_STOCK,
    )

    async with session_factory() as db:
        db_user = await db.get(User, user.id)
        order = await OrderService(db).create(db_user, await _order_payload(product.sku))
        await db.commit()
        assert order.organization_id is None
        assert await OrderService(db).get(db_user, order.id, as_manager=False)

    async with session_factory() as db:
        db_other = await db.get(User, other.id)
        with pytest.raises(OrderNotFoundError):
            await OrderService(db).get(db_other, order.id, as_manager=False)


async def test_fingerprint_separates_organization_context(session_factory):
    organization = await create_organization(session_factory, legal_name="Fingerprint Org")
    payload = await _order_payload("FINGERPRINT-1")
    legacy_hash = order_request_fingerprint(payload)
    organization_hash = order_request_fingerprint(
        payload, organization_id=organization.id
    )
    assert legacy_hash != organization_hash
