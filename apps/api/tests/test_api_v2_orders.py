"""Focused contract tests for the authenticated v2 order collection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.enums import OrganizationRole, OrderStatus, UserRole
from app.models.order import Order, OrderItem
from tests.conftest import (
    add_organization_membership,
    create_organization,
    create_user,
    set_active_organization,
)

PASSWORD = "Passw0rd!"
EMAIL = "v2-orders-client@example.by"


async def _login(api_client, email: str = EMAIL):
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _seed_order(
    session_factory,
    *,
    client,
    organization_id=None,
    status: OrderStatus = OrderStatus.NEW,
    created_at: datetime,
    total: str = "125.50",
    seq: int | None = None,
    notes: str | None = None,
) -> Order:
    async with session_factory() as session:
        order = Order(
            client_id=client.id,
            organization_id=organization_id,
            status=status,
            currency_code="BYN",
            exchange_rate="1.0000",
            rate_source="BYN",
            total_amount=total,
            created_at=created_at,
            updated_at=created_at,
            seq=seq,
            notes=notes,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def _seed_order_item(
    session_factory,
    order: Order,
    *,
    sku: str,
    name: str,
    quantity: int = 2,
    unit_price: str = "10.00",
) -> None:
    async with session_factory() as session:
        session.add(
            OrderItem(
                order_id=order.id,
                product_snapshot={"sku": sku, "name": name},
                quantity=quantity,
                unit_price=unit_price,
                currency_code="BYN",
            )
        )
        await session.commit()


async def test_list_orders_success_envelope_string_money_and_summary_projection(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await _seed_order(
        session_factory,
        client=user,
        created_at=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
    )
    await _login(api_client)

    response = await api_client.get(
        "/api/v2/orders", headers={"X-Request-ID": "v2-order-list-001"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {
        "requestId": "v2-order-list-001",
        "nextCursor": None,
        "hasMore": False,
        "limit": 50,
        "sort": "createdAt,id",
    }
    order = body["data"][0]
    assert order["total"] == {"amount": "125.50", "currency": "BYN"}
    assert order["exchangeRate"] == {
        "value": "1.0000",
        "scale": 4,
        "source": "BYN",
    }
    assert set(order) == {
        "id",
        "sequence",
        "organizationId",
        "initiatedByUserId",
        "status",
        "total",
        "exchangeRate",
        "createdAt",
        "updatedAt",
        "version",
    }
    assert "lines" not in order
    assert "photoKey" not in order
    assert "clientName" not in order


async def test_list_orders_status_filter_and_two_cursor_pages_have_no_duplicates(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    base = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    first = await _seed_order(session_factory, client=user, created_at=base)
    second = await _seed_order(
        session_factory, client=user, created_at=base + timedelta(minutes=1)
    )
    third = await _seed_order(
        session_factory,
        client=user,
        status=OrderStatus.COMPLETED,
        created_at=base + timedelta(minutes=2),
    )
    await _login(api_client)

    filtered = await api_client.get(
        "/api/v2/orders", params={"status": "COMPLETED"}
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["data"]] == [str(third.id)]

    page_one = await api_client.get("/api/v2/orders", params={"limit": 1})
    page_two = await api_client.get(
        "/api/v2/orders",
        params={
            "limit": 1,
            "cursor": page_one.json()["meta"]["nextCursor"],
        },
    )
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["meta"]["hasMore"] is True
    assert page_two.json()["meta"]["hasMore"] is True
    ids = [item["id"] for item in page_one.json()["data"] + page_two.json()["data"]]
    assert len(ids) == len(set(ids)) == 2
    assert ids == [str(third.id), str(second.id)]
    assert first.id not in ids  # the status-filtered order is still a separate check


async def test_list_orders_rejects_invalid_cursor_with_problem_details(
    api_client, session_factory
):
    await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await _login(api_client)

    response = await api_client.get("/api/v2/orders", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["detail"] == "Курсор пагинации недействителен"


async def test_list_orders_requires_authentication(api_client):
    response = await api_client.get(
        "/api/v2/orders", headers={"X-Request-ID": "v2-order-list-auth-001"}
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["requestId"] == "v2-order-list-auth-001"
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_active_organization_scope_exposes_member_owner_orders_and_legacy_fallback(
    api_client, session_factory
):
    owner = await create_user(
        session_factory, email="v2-owner@example.by", role=UserRole.CLIENT, password=PASSWORD
    )
    member = await create_user(
        session_factory, email="v2-member@example.by", role=UserRole.CLIENT, password=PASSWORD
    )
    outsider = await create_user(
        session_factory, email="v2-outsider@example.by", role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name="V2 Orders Org")
    await add_organization_membership(
        session_factory,
        user=owner,
        organization=organization,
        role=OrganizationRole.OWNER,
        is_primary=True,
    )
    await add_organization_membership(
        session_factory,
        user=member,
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    await set_active_organization(session_factory, user=owner, organization=organization)
    base = datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)
    org_order = await _seed_order(
        session_factory,
        client=member,
        organization_id=organization.id,
        created_at=base,
    )
    legacy_owner = await _seed_order(
        session_factory, client=owner, created_at=base + timedelta(minutes=1)
    )
    legacy_outsider = await _seed_order(
        session_factory, client=outsider, created_at=base + timedelta(minutes=2)
    )

    await _login(api_client, owner.email)
    response = await api_client.get("/api/v2/orders")
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["data"]} == {
        str(org_order.id),
        str(legacy_owner.id),
    }
    assert legacy_outsider.id not in {item["id"] for item in response.json()["data"]}

    await _login(api_client, outsider.email)
    outsider_response = await api_client.get("/api/v2/orders")
    assert outsider_response.status_code == 200, outsider_response.text
    outsider_ids = {item["id"] for item in outsider_response.json()["data"]}
    assert str(org_order.id) not in outsider_ids
    assert str(legacy_owner.id) not in outsider_ids
    assert str(legacy_outsider.id) in outsider_ids


async def test_without_active_organization_only_current_users_legacy_orders_are_visible(
    api_client, session_factory
):
    current = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    other = await create_user(
        session_factory, email="v2-other@example.by", role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name="Unselected Org")
    base = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    own_legacy = await _seed_order(session_factory, client=current, created_at=base)
    own_org = await _seed_order(
        session_factory, client=current, organization_id=organization.id, created_at=base
    )
    other_legacy = await _seed_order(
        session_factory, client=other, created_at=base + timedelta(minutes=1)
    )

    await _login(api_client)
    response = await api_client.get("/api/v2/orders")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(own_legacy.id)]
    assert str(own_org.id) not in {item["id"] for item in response.json()["data"]}
    assert str(other_legacy.id) not in {item["id"] for item in response.json()["data"]}


async def test_organization_scope_is_bound_to_cursor_context(api_client, session_factory):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name="Cursor Org")
    await add_organization_membership(
        session_factory, user=user, organization=organization, role=OrganizationRole.OWNER
    )
    base = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)
    for index in range(2):
        await _seed_order(
            session_factory,
            client=user,
            organization_id=organization.id,
            created_at=base + timedelta(minutes=index),
        )
    await set_active_organization(session_factory, user=user, organization=organization)
    await _login(api_client)
    first = await api_client.get("/api/v2/orders", params={"limit": 1})
    cursor = first.json()["meta"]["nextCursor"]

    active_page = await api_client.get(
        "/api/v2/orders", params={"limit": 1, "cursor": cursor}
    )
    assert active_page.status_code == 200

    async with session_factory() as session:
        db_user = await session.get(type(user), user.id)
        db_user.active_organization_id = None
        await session.commit()
    wrong_context = await api_client.get(
        "/api/v2/orders", params={"limit": 1, "cursor": cursor}
    )
    assert wrong_context.status_code == 422
    assert wrong_context.json()["code"] == "VALIDATION_ERROR"


async def test_list_orders_q_finds_by_sequence_item_sku_name_and_comment(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    base = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    by_seq = await _seed_order(
        session_factory, client=user, created_at=base, seq=4101
    )
    by_item = await _seed_order(
        session_factory, client=user, created_at=base + timedelta(minutes=1)
    )
    await _seed_order_item(
        session_factory, by_item, sku="KBL-777", name="Кабель медный ВВГнг"
    )
    by_comment = await _seed_order(
        session_factory,
        client=user,
        created_at=base + timedelta(minutes=2),
        notes="Вход через северную проходную",
    )
    await _login(api_client)

    response = await api_client.get("/api/v2/orders", params={"q": "4101"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(by_seq.id)]

    response = await api_client.get("/api/v2/orders", params={"q": "kbl-777"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(by_item.id)]

    response = await api_client.get("/api/v2/orders", params={"q": "медный"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(by_item.id)]

    response = await api_client.get("/api/v2/orders", params={"q": "проходную"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(by_comment.id)]

    empty = await api_client.get("/api/v2/orders", params={"q": "zzz-no-match"})
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] == []
    assert empty.json()["meta"]["hasMore"] is False
    assert empty.json()["meta"]["nextCursor"] is None


async def test_list_orders_q_treats_like_wildcards_literally(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    base = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    underscore = await _seed_order(
        session_factory, client=user, created_at=base
    )
    await _seed_order_item(session_factory, underscore, sku="A_B", name="Скоба")
    plain = await _seed_order(
        session_factory, client=user, created_at=base + timedelta(minutes=1)
    )
    await _seed_order_item(session_factory, plain, sku="AXB", name="Анкер")
    await _login(api_client)

    # «%» ищется буквально: «10%» не превращается в «начинается с 10».
    response = await api_client.get("/api/v2/orders", params={"q": "10%"})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == []

    # «_» тоже буквально: «a_b» не матчит «AXB».
    response = await api_client.get("/api/v2/orders", params={"q": "a_b"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [str(underscore.id)]


async def test_list_orders_date_range_is_inclusive_of_whole_end_day(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    before = await _seed_order(
        session_factory,
        client=user,
        created_at=datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc),
    )
    day_start = await _seed_order(
        session_factory,
        client=user,
        created_at=datetime(2026, 9, 20, 0, 0, 0, 1, tzinfo=timezone.utc),
    )
    day_end = await _seed_order(
        session_factory,
        client=user,
        created_at=datetime(2026, 9, 20, 23, 59, 59, tzinfo=timezone.utc),
    )
    after = await _seed_order(
        session_factory,
        client=user,
        created_at=datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc),
    )
    await _login(api_client)

    response = await api_client.get(
        "/api/v2/orders",
        params={"date_from": "2026-09-20", "date_to": "2026-09-20"},
    )
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [
        str(day_end.id),
        str(day_start.id),
    ]
    assert {before.id, after.id}.isdisjoint(
        {item["id"] for item in response.json()["data"]}
    )

    open_from = await api_client.get(
        "/api/v2/orders", params={"date_from": "2026-09-20"}
    )
    assert open_from.status_code == 200, open_from.text
    assert [item["id"] for item in open_from.json()["data"]] == [
        str(after.id),
        str(day_end.id),
        str(day_start.id),
    ]


async def test_list_orders_total_range_is_inclusive(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    base = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    low = await _seed_order(session_factory, client=user, created_at=base, total="50.00")
    middle = await _seed_order(
        session_factory, client=user, created_at=base + timedelta(minutes=1), total="100.00"
    )
    high = await _seed_order(
        session_factory, client=user, created_at=base + timedelta(minutes=2), total="150.00"
    )
    await _login(api_client)

    both = await api_client.get(
        "/api/v2/orders", params={"min_total": "50", "max_total": "100"}
    )
    assert both.status_code == 200, both.text
    assert [item["id"] for item in both.json()["data"]] == [str(middle.id), str(low.id)]

    only_min = await api_client.get("/api/v2/orders", params={"min_total": "100.01"})
    assert only_min.status_code == 200, only_min.text
    assert [item["id"] for item in only_min.json()["data"]] == [str(high.id)]

    only_max = await api_client.get("/api/v2/orders", params={"max_total": "49.99"})
    assert only_max.status_code == 200, only_max.text
    assert only_max.json()["data"] == []


async def test_list_orders_filters_are_bound_to_cursor_signature(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    base = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    older = await _seed_order(
        session_factory,
        client=user,
        created_at=base,
        notes="cursor-marker",
        total="80.00",
    )
    newer = await _seed_order(
        session_factory,
        client=user,
        created_at=base + timedelta(minutes=1),
        notes="cursor-marker",
        total="80.00",
    )
    await _seed_order(
        session_factory,
        client=user,
        created_at=base + timedelta(minutes=2),
        notes="other",
    )
    await _login(api_client)

    first = await api_client.get(
        "/api/v2/orders", params={"q": "cursor-marker", "limit": 1}
    )
    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()["data"]] == [str(newer.id)]
    assert first.json()["meta"]["hasMore"] is True
    cursor = first.json()["meta"]["nextCursor"]

    second = await api_client.get(
        "/api/v2/orders",
        params={"q": "cursor-marker", "limit": 1, "cursor": cursor},
    )
    assert second.status_code == 200, second.text
    assert [item["id"] for item in second.json()["data"]] == [str(older.id)]
    assert second.json()["meta"]["hasMore"] is False

    # Тот же курсор с другим набором фильтров отклоняется, а не тихо ищет другое.
    changed_q = await api_client.get(
        "/api/v2/orders", params={"q": "other", "limit": 1, "cursor": cursor}
    )
    assert changed_q.status_code == 422
    assert changed_q.json()["code"] == "VALIDATION_ERROR"

    changed_total = await api_client.get(
        "/api/v2/orders",
        params={"q": "cursor-marker", "min_total": "1", "limit": 1, "cursor": cursor},
    )
    assert changed_total.status_code == 422
    assert changed_total.json()["code"] == "VALIDATION_ERROR"


async def test_list_orders_rejects_invalid_filter_format_with_problem_details(
    api_client, session_factory
):
    await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await _login(api_client)

    bad_date = await api_client.get(
        "/api/v2/orders", params={"date_from": "20-09-2026"}
    )
    assert bad_date.status_code == 422, bad_date.text
    assert bad_date.headers["content-type"].startswith("application/problem+json")
    body = bad_date.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["title"] == "Ошибка валидации"
    assert body["detail"] == "Один или несколько параметров запроса некорректны"
    assert any(error["field"] == "query.date_from" for error in body["errors"])

    bad_total = await api_client.get("/api/v2/orders", params={"min_total": "abc"})
    assert bad_total.status_code == 422, bad_total.text
    assert bad_total.headers["content-type"].startswith("application/problem+json")
    total_body = bad_total.json()
    assert total_body["code"] == "VALIDATION_ERROR"
    assert any(error["field"] == "query.min_total" for error in total_body["errors"])

    negative_total = await api_client.get("/api/v2/orders", params={"max_total": "-5"})
    assert negative_total.status_code == 422, negative_total.text
    assert negative_total.json()["code"] == "VALIDATION_ERROR"
