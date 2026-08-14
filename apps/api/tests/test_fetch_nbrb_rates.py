"""Тесты загрузки курсов НБ РБ. См. ARCHITECTURE_PLAN.md §17.1.

Покрытие:
  - успешный upsert отслеживаемых валют (фильтр GBP, BYN не отслеживается);
  - fallback при ошибке HTTP + алёрт менеджеру (in-app + telegram);
  - идемпотентность on_conflict_do_update в рамках одного дня;
  - fallback без telegram-конфига (delay не вызывается).
"""
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

import app.tasks.fetch_nbrb_rates as fetch_task
import app.tasks.notifications as notif_task
from app.models.pricing import ExchangeRate
from app.models.system import Notification
from tests.conftest import set_rate

# Дата, которой датируются курсы в фейковом ответе НБ РБ.
RATES_DATE = "2024-08-14T00:00:00"


def _nbrb_payload(rates: dict | None = None) -> list[dict]:
    """Фейковый ответ НБ РБ: USD/EUR/RUB + GBP (GBP должен отфильтроваться)."""
    rates = rates or {"USD": 3.27, "EUR": 3.55, "RUB": 3.45, "GBP": 4.10}
    return [
        {"Cur_ID": 145, "Date": RATES_DATE, "Cur_Abbreviation": "USD",
         "Cur_Scale": 1, "Cur_Name": "Доллар США", "Cur_OfficialRate": rates["USD"]},
        {"Cur_ID": 292, "Date": RATES_DATE, "Cur_Abbreviation": "EUR",
         "Cur_Scale": 1, "Cur_Name": "Евро", "Cur_OfficialRate": rates["EUR"]},
        {"Cur_ID": 298, "Date": RATES_DATE, "Cur_Abbreviation": "RUB",
         "Cur_Scale": 100, "Cur_Name": "Российский рубль", "Cur_OfficialRate": rates["RUB"]},
        {"Cur_ID": 143, "Date": RATES_DATE, "Cur_Abbreviation": "GBP",
         "Cur_Scale": 1, "Cur_Name": "Фунт стерлингов", "Cur_OfficialRate": rates["GBP"]},
    ]


class _FakeTg:
    """Фейк Celery-таски send_telegram: записывает вызовы .delay()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def delay(self, chat_id: str, text: str) -> None:
        self.calls.append((chat_id, text))


@pytest.mark.asyncio
class TestFetchRates:
    async def test_success_upserts_tracked_currencies(
        self, session_factory, monkeypatch
    ):
        monkeypatch.setattr(fetch_task, "_worker_session", session_factory)

        async def _fake():
            return _nbrb_payload()

        monkeypatch.setattr(fetch_task, "_fetch_nbrb_json", _fake)

        # Вызываем async-ядро напрямую: sync-обёртка fetch_rates() зовёт
        # asyncio.run, который нельзя запустить из уже работающего loop'а
        # pytest-asyncio (тот же приём, что и test_import_csv → _run_import).
        result = await fetch_task._fetch_rates()

        assert result["status"] == "ok"
        assert result["saved"] == 3

        async with session_factory() as s:
            rates = {r.currency_code: r for r in (await s.scalars(select(ExchangeRate))).all()}
            # GBP отфильтрован, BYN не отслеживается → ровно 3 отслеживаемые валюты.
            assert set(rates) == {"USD", "EUR", "RUB"}
            assert rates["USD"].rate == Decimal("3.27")
            assert rates["USD"].scale == 1
            assert rates["EUR"].rate == Decimal("3.55")
            assert rates["RUB"].rate == Decimal("3.45")
            assert rates["RUB"].scale == 100
            assert rates["USD"].fetched_at == date(2024, 8, 14)
            # Успех → алёрта быть не должно.
            alerts = (await s.scalars(
                select(Notification).where(Notification.type == "RATE_FETCH_FAILED")
            )).all()
            assert alerts == []

    async def test_fallback_on_http_error(self, session_factory, monkeypatch):
        monkeypatch.setattr(fetch_task, "_worker_session", session_factory)
        # Старый курс, чтобы _latest_fetched_date вернул дату для текста алёрта.
        await set_rate(
            session_factory, currency="USD", rate=3.0, fetched_at=date(2024, 1, 1)
        )

        async def _raises():
            raise httpx.HTTPError("boom")

        monkeypatch.setattr(fetch_task, "_fetch_nbrb_json", _raises)

        # Перехват lazy-import внутри _fallback_alert (модульный атрибут).
        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)
        monkeypatch.setattr(fetch_task.settings, "telegram_manager_chat_id", "999")

        result = await fetch_task._fetch_rates()

        assert result["status"] == "fallback"
        async with session_factory() as s:
            alerts = (await s.scalars(
                select(Notification).where(Notification.type == "RATE_FETCH_FAILED")
            )).all()
            assert len(alerts) == 1
            assert alerts[0].user_id is None  # всем менеджерам (§20)
            assert "telegram" in alerts[0].channel

        assert len(fake_tg.calls) == 1
        chat_id, text = fake_tg.calls[0]
        assert chat_id == "999"
        assert "2024-01-01" in text  # последний курс от этой даты

    async def test_idempotent_rerun_same_day(self, session_factory, monkeypatch):
        monkeypatch.setattr(fetch_task, "_worker_session", session_factory)

        payloads = iter([
            _nbrb_payload(),
            _nbrb_payload(rates={"USD": 3.31, "EUR": 3.55, "RUB": 3.45, "GBP": 4.10}),
        ])

        async def _fake():
            return next(payloads)

        monkeypatch.setattr(fetch_task, "_fetch_nbrb_json", _fake)

        await fetch_task._fetch_rates()
        await fetch_task._fetch_rates()

        async with session_factory() as s:
            rates = (await s.scalars(select(ExchangeRate))).all()
            assert len(rates) == 3  # дублей нет — по одной строке на валюту
            by_code = {r.currency_code: r for r in rates}
            assert by_code["USD"].rate == Decimal("3.31")  # rate обновлён

    async def test_fallback_without_telegram_config(
        self, session_factory, monkeypatch
    ):
        monkeypatch.setattr(fetch_task, "_worker_session", session_factory)

        async def _raises():
            raise httpx.HTTPError("boom")

        monkeypatch.setattr(fetch_task, "_fetch_nbrb_json", _raises)

        fake_tg = _FakeTg()
        monkeypatch.setattr(notif_task, "send_telegram", fake_tg)
        monkeypatch.setattr(fetch_task.settings, "telegram_manager_chat_id", "")

        result = await fetch_task._fetch_rates()

        assert result["status"] == "fallback"
        async with session_factory() as s:
            alerts = (await s.scalars(
                select(Notification).where(Notification.type == "RATE_FETCH_FAILED")
            )).all()
            assert len(alerts) == 1
        assert fake_tg.calls == []  # без конфига → delay не зовётся
