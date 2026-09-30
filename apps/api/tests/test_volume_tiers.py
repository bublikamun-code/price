"""Скидки за объём: правила §8 и чистые функции лестницы (§16 п.41).

Покрывают канон:
  * «лучшая подходящая» ступень на **границах** количества (qty-1, qty, qty+1);
  * ступени не суммируются («от 10 −2%, от 50 −5%» на 50 шт → −5%, не −7%);
  * скидка по бренду и за объём — **максимум из двух**, не сумма;
  * ``override_price`` не подвержен объёмной скидке (§8 п.1);
  * в каталоге объёмная скидка не применяется (количество неизвестно).

Redis в тестах замокан на cache-мимо: лестницы кэшируются по тегу
``volume-tiers``, но проверяется именно выбор ступени, а не работа Redis.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.repositories.volume_tiers import effective_discount_percent, pick_tier


def _ladder(*pairs: tuple[int, str]) -> list[dict]:
    """Лестница в том виде, в каком её отдаёт PricingService (по возрастанию)."""
    return [{"min_qty": q, "discount_percent": float(p)} for q, p in pairs]


LADDER = _ladder((10, "2"), (50, "5"), (100, "9"))


# ------------------------------------------------------------ выбор ступени
@pytest.mark.parametrize(
    ("quantity", "expected_min_qty"),
    [
        (None, None),      # количество неизвестно (каталог) — ступени нет
        (0, None),        # нечего тарифицировать
        (1, None),        # ниже первого порога
        (9, None),        # на единицу ниже порога
        (10, 10),         # ровно на пороге — порог включительный
        (11, 10),         # выше порога, до следующего
        (49, 10),
        (50, 50),         # второй порог
        (99, 50),
        (100, 100),       # третий порог
        (10_000, 100),    # дальше верхней ступени
    ],
)
def test_pick_tier_boundaries(quantity, expected_min_qty):
    chosen = pick_tier(LADDER, quantity)
    if expected_min_qty is None:
        assert chosen is None
    else:
        assert chosen["min_qty"] == expected_min_qty


def test_pick_tier_empty_ladder():
    assert pick_tier([], 100) is None


def test_pick_tier_does_not_sum_stages():
    """«От 50 шт» — это −5%, а не −2% + −5% (§8)."""
    chosen = pick_tier(LADDER, 50)
    assert Decimal(str(chosen["discount_percent"])) == Decimal("5")


def test_pick_tier_prefers_reachable_over_larger_percent():
    """Проценты могут убывать с ростом порога: важна достижимость, а не максимум.

    Редактор менеджера не запрещает такую лестницу, а считать по ней всё
    равно нужно: иначе товар, купленный 10 шт, получил бы −7% от недостижимой
    ступени.
    """
    ladder = _ladder((10, "7"), (50, "5"))
    assert pick_tier(ladder, 10)["discount_percent"] == 7.0
    assert pick_tier(ladder, 50)["discount_percent"] == 5.0


# ------------------------------------------------- максимум из двух скидок
@pytest.mark.parametrize(
    ("brand", "tier", "expected"),
    [
        (None, None, None),        # скидок нет вообще
        (Decimal("5"), None, Decimal("5")),      # только бренд
        (None, Decimal("7"), Decimal("7")),      # только объём
        (Decimal("5"), Decimal("7"), Decimal("7")),   # объём больше
        (Decimal("9"), Decimal("7"), Decimal("9")),   # бренд больше
        (Decimal("7"), Decimal("7"), Decimal("7")),   # равны — не складываются
        (Decimal("0"), Decimal("7"), Decimal("7")),   # нулевой бренд не мешает
    ],
)
def test_effective_discount_is_max_not_sum(brand, tier, expected):
    assert effective_discount_percent(brand, tier) == expected


# --------------------------------------------------- client_price_byn (§8)
def test_override_price_beats_volume_discount():
    """Жёсткая цена из CSV перекрывает обе скидки (§8 п.1).

    Иначе одна и та же цена в прайсе означала бы разные вещи в зависимости от
    количества, а импорт этого выразить не может.
    """
    from app.services.pricing import client_price_byn

    assert client_price_byn(100, Decimal("77.00"), Decimal("20")) == Decimal("77.00")


def test_volume_discount_applies_to_base_price():
    from app.services.pricing import client_price_byn

    assert client_price_byn(100, None, Decimal("5")) == Decimal("95.00")
    assert client_price_byn(100, None, None) == Decimal("100.00")
