"""apply-csv кросс-справочника: отчёт и наполнение корзины v2 (§16 п.43, этап 7).

Покрывает: matched (регистронезависимо, дефолт qty, таб из Excel) с клиентскими
ценами и resolved product UUID, повторный apply = инкремент qty корзины,
unknown без маппинга и ARCHIVED-товар в маппинге (корзина не тронута), дубль
артикула в файле → AMBIGUOUS при частичном успехе, валидация CSV (пустой /
>500 / некорректное qty), комментарии и пустые строки, cartVersion == ETag
корзины.
"""
from __future__ import annotations

from app.models.catalog import Product
from app.models.enums import OrganizationRole, StockStatus, UserRole
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
)

PASSWORD = "Passw0rd!"
BUYER_EMAIL = "csku-apply-buyer@example.by"

MAPPINGS_URL = "/api/v2/me/organization/client-sku-mappings"
APPLY_URL = f"{MAPPINGS_URL}/apply-csv"
CART_URL = "/api/v2/cart"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _seed_buyer_with_cart_scope(session_factory, *, legal_name: str):
    user = await create_user(
        session_factory, email=BUYER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name=legal_name)
    await add_organization_membership(
        session_factory, user=user, organization=organization, role=OrganizationRole.BUYER
    )
    await set_active_organization(
        session_factory, user=user, organization=organization
    )
    return user, organization


async def _create_mapping(api_client, *, client_sku: str, product) -> dict:
    response = await api_client.post(
        MAPPINGS_URL,
        json={"clientSku": client_sku, "productId": str(product.id), "note": None},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _cart_line_quantities(api_client) -> dict[str, int]:
    """{productId: quantity} текущей корзины v2."""
    response = await api_client.get(CART_URL)
    assert response.status_code == 200, response.text
    return {item["productId"]: item["quantity"] for item in response.json()["data"]["items"]}


async def test_apply_csv_matched_fills_cart_with_prices(api_client, session_factory):
    """Три matched строки (регистр, `=qty`, дефолт, таб) → корзина, цены, UUID."""
    _user, organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Org"
    )
    brand = await create_brand(session_factory, name="Apply Brand")
    product_a = await create_product(
        session_factory, sku="VENT-2", name="Привод ГТУ-2", brand=brand, base_price=100
    )
    product_b = await create_product(
        session_factory, sku="VENT-3", name="Привод ГТУ-3", brand=brand, base_price=250.5
    )
    product_c = await create_product(
        session_factory, sku="MTR-12", name="Мотор 12", brand=brand, base_price=80
    )
    await _login(api_client, BUYER_EMAIL)
    # Связки созданы в другом регистре, чем строки файла (CITEXT).
    await _create_mapping(api_client, client_sku="вент", product=product_a)
    await _create_mapping(api_client, client_sku="vent", product=product_b)
    await _create_mapping(api_client, client_sku="МОТОР", product=product_c)

    csv_text = "Вент=5\nVENT\nмотор\t2"
    applied = await api_client.post(APPLY_URL, json={"csv": csv_text})
    assert applied.status_code == 200, applied.text

    data = applied.json()["data"]
    assert data["summary"] == {"matched": 3, "unknown": 0, "ambiguous": 0, "cartAdded": 3}
    assert data["cartVersion"] is not None

    rows = data["rows"]
    assert [row["status"] for row in rows] == ["MATCHED", "MATCHED", "MATCHED"]
    assert [row["qty"] for row in rows] == [5, 1, 2]  # дефолт qty=1 без qty
    assert [row["clientSku"] for row in rows] == ["Вент", "VENT", "мотор"]
    # Resolved product UUID обязателен (урок из API_V2_CONTRACT §10).
    assert [row["productId"] for row in rows] == [
        str(product_a.id),
        str(product_b.id),
        str(product_c.id),
    ]
    assert [row["productSku"] for row in rows] == ["VENT-2", "VENT-3", "MTR-12"]
    assert [row["productName"] for row in rows] == [
        "Привод ГТУ-2",
        "Привод ГТУ-3",
        "Мотор 12",
    ]
    # Клиентские цены — канонические Money-строки.
    assert [row["unitPrice"] for row in rows] == [
        {"amount": "100.00", "currency": "BYN"},
        {"amount": "250.50", "currency": "BYN"},
        {"amount": "80.00", "currency": "BYN"},
    ]
    assert [row["stockStatus"] for row in rows] == ["IN_STOCK", "IN_STOCK", "IN_STOCK"]

    quantities = await _cart_line_quantities(api_client)
    assert quantities == {
        str(product_a.id): 5,
        str(product_b.id): 1,
        str(product_c.id): 2,
    }


async def test_apply_csv_repeat_increments_cart_lines(api_client, session_factory):
    """Повторный apply по тому же файлу инкрементит qty (штатная семантика корзины)."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Repeat Org"
    )
    brand = await create_brand(session_factory, name="Apply Repeat Brand")
    product = await create_product(
        session_factory, sku="VENT-R", name="Привод R", brand=brand, base_price=100
    )
    await _login(api_client, BUYER_EMAIL)
    await _create_mapping(api_client, client_sku="вент", product=product)

    first = await api_client.post(APPLY_URL, json={"csv": "Вент=5\n"})
    assert first.status_code == 200, first.text
    assert await _cart_line_quantities(api_client) == {str(product.id): 5}

    second = await api_client.post(APPLY_URL, json={"csv": "Вент=5\n"})
    assert second.status_code == 200, second.text
    assert second.json()["data"]["summary"]["cartAdded"] == 1
    assert await _cart_line_quantities(api_client) == {str(product.id): 10}


async def test_apply_csv_unknown_and_archived_leave_cart_untouched(
    api_client, session_factory
):
    """Нет маппинга и ARCHIVED-товар в маппинге → UNKNOWN, корзина пуста."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Unknown Org"
    )
    brand = await create_brand(session_factory, name="Apply Unknown Brand")
    later_archived = await create_product(
        session_factory, sku="VENT-ARC2", name="Архивный привод", brand=brand,
        base_price=100,
    )
    await _login(api_client, BUYER_EMAIL)
    # Маппинг создаётся на живой товар, архивируется позже — так проходит
    # реальный жизненный цикл (создание на ARCHIVED отсекает 422).
    await _create_mapping(api_client, client_sku="архив", product=later_archived)
    async with session_factory() as s:
        stored = await s.get(Product, later_archived.id)
        stored.stock_status = StockStatus.ARCHIVED
        await s.commit()


    applied = await api_client.post(
        APPLY_URL, json={"csv": "нет-такого=3\nархив\t1\n"}
    )
    assert applied.status_code == 200, applied.text

    data = applied.json()["data"]
    assert data["summary"] == {"matched": 0, "unknown": 2, "ambiguous": 0, "cartAdded": 0}
    assert data["cartVersion"] is None  # ни одна строка не попала в корзину
    assert [row["status"] for row in data["rows"]] == ["UNKNOWN", "UNKNOWN"]
    assert data["rows"][0]["message"] == "Не найден в справочнике"
    assert data["rows"][1]["message"] == "Товар в архиве"
    # Маппинг сохраняется — клиент перемапит (§16 п.43 п.4).
    assert data["rows"][1]["productId"] is None
    assert await _cart_line_quantities(api_client) == {}


async def test_apply_csv_duplicate_in_file_is_ambiguous(api_client, session_factory):
    """Дубль артикула в файле → все вхождения AMBIGUOUS, остальные применены."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Dup Org"
    )
    brand = await create_brand(session_factory, name="Apply Dup Brand")
    product = await create_product(
        session_factory, sku="VENT-D", name="Привод D", brand=brand, base_price=100
    )
    other = await create_product(
        session_factory, sku="MTR-D", name="Мотор D", brand=brand, base_price=50
    )
    await _login(api_client, BUYER_EMAIL)
    await _create_mapping(api_client, client_sku="вент", product=product)
    await _create_mapping(api_client, client_sku="мотор", product=other)

    # «вент» и «ВЕНТ» — один артикул без регистра: оба вхождения AMBIGUOUS.
    applied = await api_client.post(
        APPLY_URL, json={"csv": "вент=3\nВЕНТ=4\nмотор\t2\n"}
    )
    assert applied.status_code == 200, applied.text

    data = applied.json()["data"]
    assert data["summary"] == {"matched": 1, "unknown": 0, "ambiguous": 2, "cartAdded": 1}
    statuses = [row["status"] for row in data["rows"]]
    assert statuses == ["AMBIGUOUS", "AMBIGUOUS", "MATCHED"]
    assert all(row["message"] for row in data["rows"][:2])
    # qty дублей молча не суммируется: в корзине только «мотор».
    assert await _cart_line_quantities(api_client) == {str(other.id): 2}
    assert data["rows"][2]["productId"] == str(other.id)


async def test_apply_csv_empty_and_too_many_rows_422(api_client, session_factory):
    """Пустой CSV и >500 позиций → 422 VALIDATION_ERROR (файл не применён)."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply 422 Org"
    )
    await _login(api_client, BUYER_EMAIL)

    comments_only = await api_client.post(
        APPLY_URL, json={"csv": "# только комментарий\n\n   \n"}
    )
    assert comments_only.status_code == 422, comments_only.text
    assert comments_only.json()["code"] == "VALIDATION_ERROR"

    too_many = await api_client.post(
        APPLY_URL, json={"csv": "\n".join(f"sku-{i}" for i in range(501))}
    )
    assert too_many.status_code == 422, too_many.text
    assert too_many.json()["code"] == "VALIDATION_ERROR"
    assert "500" in too_many.json()["detail"]


async def test_apply_csv_invalid_qty_row_reported_not_fatal(api_client, session_factory):
    """qty 0 → строка UNKNOWN «Некорректное количество», файл не валим."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Qty Org"
    )
    brand = await create_brand(session_factory, name="Apply Qty Brand")
    product = await create_product(
        session_factory, sku="VENT-Q", name="Привод Q", brand=brand, base_price=100
    )
    await _login(api_client, BUYER_EMAIL)
    await _create_mapping(api_client, client_sku="вент", product=product)

    applied = await api_client.post(
        APPLY_URL, json={"csv": "вент=0\nвент\t3\n"}
    )
    assert applied.status_code == 200, applied.text

    data = applied.json()["data"]
    assert data["summary"] == {"matched": 1, "unknown": 1, "ambiguous": 0, "cartAdded": 1}
    assert data["rows"][0]["status"] == "UNKNOWN"
    assert data["rows"][0]["message"] == "Некорректное количество"
    assert data["rows"][1]["status"] == "MATCHED"
    assert await _cart_line_quantities(api_client) == {str(product.id): 3}


async def test_apply_csv_skips_comments_and_blank_lines(api_client, session_factory):
    """Пустые строки и `#`-комментарии пропускаются (§16 п.43 п.5)."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Comments Org"
    )
    brand = await create_brand(session_factory, name="Apply Comments Brand")
    product = await create_product(
        session_factory, sku="VENT-C", name="Привод C", brand=brand, base_price=100
    )
    await _login(api_client, BUYER_EMAIL)
    await _create_mapping(api_client, client_sku="вент", product=product)

    applied = await api_client.post(
        APPLY_URL,
        json={"csv": "# закупка от 01.11\n\n   \nвент=2\n# хвост\n"},
    )
    assert applied.status_code == 200, applied.text

    data = applied.json()["data"]
    assert data["summary"] == {"matched": 1, "unknown": 0, "ambiguous": 0, "cartAdded": 1}
    assert [row["clientSku"] for row in data["rows"]] == ["вент"]
    assert await _cart_line_quantities(api_client) == {str(product.id): 2}


async def test_apply_csv_cart_version_matches_cart_etag(api_client, session_factory):
    """cartVersion — версия корзины после последней мутации (значение ETag)."""
    _user, _organization = await _seed_buyer_with_cart_scope(
        session_factory, legal_name="Csku Apply Etag Org"
    )
    brand = await create_brand(session_factory, name="Apply Etag Brand")
    product = await create_product(
        session_factory, sku="VENT-E", name="Привод E", brand=brand, base_price=100
    )
    await _login(api_client, BUYER_EMAIL)
    await _create_mapping(api_client, client_sku="вент", product=product)

    applied = await api_client.post(APPLY_URL, json={"csv": "вент=4\n"})
    assert applied.status_code == 200, applied.text
    cart_version = applied.json()["data"]["cartVersion"]
    assert cart_version is not None

    cart = await api_client.get(CART_URL)
    assert cart.status_code == 200, cart.text
    assert cart.headers["ETag"] == f'"{cart_version}"'
