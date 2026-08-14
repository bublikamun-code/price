"""Unit-тесты конвертера Bitrix → товар (app.importers.optibox).

Без БД: проверяем нормализацию строки выгрузки 1С-Битрикс.
Колонки — коды свойств Битрикса (см. заголовок листа «OptiBox Pro»).
"""
from app.importers.optibox import row_to_product

# Реалистичная строка выгрузки (по мотивам OptiBox_Pro_Belarus.xlsx).
SAMPLE_ROW = {
    "IP_PROP112": "379782",
    "IE_XML_ID": None,
    "IE_NAME": "Корпус пластиковый OptiBox Pro 8-NNR-IP40",
    "IP_PROP130": "8",
    "IP_PROP504": "Pro",
    "IP_PROP505": None,
    "IP_PROP507": "Белый",
    "IP_PROP509": "KEAZ",
    "IP_PROP514": None,
    "IP_PROP538": "OptiBox Pro",
    "IP_PROP540": "249",
    "IP_PROP553": "109",
    "IP_PROP554": "327",
    "IP_PROP132": "9 016",
    "IP_PROP133": "распределительный",
    "IP_PROP142": None,
    "IP_PROP144": None,
    "IP_PROP145": "Корпус пластиковый",
    "IP_PROP151": "IK09",
    "IP_PROP152": "пластик",
    "IP_PROP164": None,
    "IP_PROP165": None,
    "IP_PROP166": "нет",
    "IP_PROP168": "от -25°С до +65°С",
    "IP_PROP177": "DIN-рейка",
    "IP_PROP184": "IP40",
    "CP_QUANTITY": "1 шт",
    "IE_PREVIEW_PICTURE": "https://files.keaz.ru/f/77429/118036.1495_big.jpg",
}


def test_basic_mapping():
    p = row_to_product(SAMPLE_ROW)
    assert p["sku"] == "379782"
    assert p["name"] == "Корпус пластиковый OptiBox Pro 8-NNR-IP40"
    assert p["brand"] == "KEAZ"
    assert p["series"] == "OptiBox Pro"
    assert p["photo_url"] == "https://files.keaz.ru/f/77429/118036.1495_big.jpg"


def test_modules_extracted_from_name_as_int():
    p = row_to_product(SAMPLE_ROW)
    assert p["attributes"]["modules"] == 8
    assert isinstance(p["attributes"]["modules"], int)


def test_modules_absent_when_name_has_no_number():
    """Имя без числа (мультимедийный корпус) → modules не задаём, колонке не верим."""
    row = {**SAMPLE_ROW, "IE_NAME": "Корпус пластиковый OptiBox Pro"}
    p = row_to_product(row)
    assert "modules" not in p["attributes"]
    # TEST-цена для не-модульных — плоская 30.00
    assert p["base_price"] == 30.00


def test_key_attributes_present():
    p = row_to_product(SAMPLE_ROW)
    a = p["attributes"]
    assert a["color"] == "Белый"
    assert a["ip_rating"] == "IP40"
    assert a["ik_rating"] == "IK09"
    assert a["material"] == "пластик"
    assert a["mounting_type"] == "Корпус пластиковый"
    assert a["temperature_range"] == "от -25°С до +65°С"
    assert a["din_rail"] == "DIN-рейка"
    assert a["purpose"] == "распределительный"
    assert a["unit"] == "1 шт"
    assert a["transparent_window"] == "нет"


def test_dimensions_and_weight_as_numbers():
    p = row_to_product(SAMPLE_ROW)
    a = p["attributes"]
    assert a["dimensions_mm"] == [249, 109, 327]
    assert a["weight_g"] == 9016  # «9 016» → int


def test_photo_url_duplicated_into_attributes():
    p = row_to_product(SAMPLE_ROW)
    assert p["attributes"]["photo_url"] == p["photo_url"]


def test_test_base_price_formula():
    # 8 модулей → 8 + 1.8*8 = 22.40 BYN
    p8 = row_to_product(SAMPLE_ROW)
    assert p8["base_price"] == 22.40
    # 12 модулей → 8 + 1.8*12 = 29.60
    row12 = {**SAMPLE_ROW, "IE_NAME": "Корпус OptiBox Pro 12-NNR-IP40", "IP_PROP130": "12"}
    assert row_to_product(row12)["base_price"] == 29.60
    # 60 модулей → 8 + 1.8*60 = 116.00
    row60 = {**SAMPLE_ROW, "IE_NAME": "Корпус OptiBox Pro 60-NNR-IP40", "IP_PROP130": "60"}
    assert row_to_product(row60)["base_price"] == 116.00


def test_empty_optionals_omitted():
    row = {k: None for k in SAMPLE_ROW}
    row["IP_PROP112"] = "123"
    row["IE_NAME"] = "Корпус OptiBox Pro 8-X-IP40"
    p = row_to_product(row)
    a = p["attributes"]
    # модули есть (из имени), остального нет → ключи отсутствуют
    assert a.get("modules") == 8
    for absent in ("color", "ip_rating", "material", "dimensions_mm", "weight_g", "photo_url"):
        assert absent not in a
    assert p["base_price"] == 22.40
