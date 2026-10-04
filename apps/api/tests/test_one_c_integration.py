"""Заглушки интеграции с 1С (§18): контракт, выбор реализации, HTTP-ручки.

Что здесь защищается:
  * заглушка **никогда** не падает «молча» и **никогда** не ходит в сеть;
  * фабрика выбирает реализацию строго по настройкам и не бросает исключений
    (приложение обязано стартовать при любых настройках);
  * отсутствие настроек не роняет импорт ``app.main`` — то есть исчезновение
    try/except-заглушки не сломало старт;
  * ручки /api/integrations/1c/** отвечают по контракту: 503 «не настроено»,
    401/403 на авторизации, 501 «спроектировано, но не реализовано» (§18.2).

Тесты без БД: ручки интеграции не ходят в БД, клиент — заглушка.
"""
import httpx
import pytest

from app.api.v1.integrations import one_c as one_c_api
from app.core.config import settings
from app.integrations.one_c import (
    HttpOneCClient,
    OneCAuthError,
    OneCClient,
    OneCError,
    OneCNotConfiguredError,
    OneCResponseError,
    OneCTransportError,
    OrderExportRequest,
    OrderExportResult,
    OrderStatusRequest,
    OrderStatusResult,
    StubOneCClient,
    create_one_c_client,
    describe_one_c_state,
    get_one_c_client,
    missing_outbound_settings,
    reset_one_c_client,
)
from app.integrations.one_c.stub import NOT_CONFIGURED_MESSAGE
from app.main import app
from app.schemas.commerceml import SCHEMA_VERSION, OrderStatusChange

TOKEN = "test-1c-token"


# ---------- Заглушка: поведение «не настроено» ----------
class TestStubClient:
    async def test_export_orders_reports_not_configured(self):
        """Отказ понятен: в тексте есть действие и подсказка, что задать."""
        client = StubOneCClient()
        with pytest.raises(OneCNotConfiguredError) as exc_info:
            await client.export_orders(OrderExportRequest())

        message = str(exc_info.value)
        assert "Интеграция с 1С не настроена" in message
        assert "выгрузка заказов" in message
        assert "INTEGRATION_1C_ENABLED=true" in message
        assert "INTEGRATION_1C_BASE_URL" in message

    async def test_push_order_status_reports_not_configured(self):
        client = StubOneCClient()
        change = OrderStatusChange.model_validate(
            {
                "stamp": {"date": "2026-01-01T00:00:00Z"},
                "external_id": "УТ-000012",
                "status": "shipped",
                "changed_at": "2026-01-02T10:00:00Z",
            }
        )
        with pytest.raises(OneCNotConfiguredError) as exc_info:
            await client.push_order_status(OrderStatusRequest(change=change))

        message = str(exc_info.value)
        assert "возврат статуса заказа" in message
        # Ошибка 1С-обмена — подкласс базовой, роутер ловит общий тип
        assert isinstance(exc_info.value, OneCError)

    async def test_custom_reason_is_used_verbatim(self):
        """Причину задаёт фабрика — она попадает в сообщение без переписывания."""
        client = StubOneCClient(reason="не задано INTEGRATION_1C_BASE_URL")
        with pytest.raises(OneCNotConfiguredError) as exc_info:
            await client.export_orders(OrderExportRequest())
        assert "не задано INTEGRATION_1C_BASE_URL" in str(exc_info.value)

    def test_stub_is_never_configured(self):
        assert StubOneCClient().configured is False

    async def test_stub_makes_no_network_calls(self, monkeypatch):
        """Главная гарантия заглушки: ни одного TCP-соединения."""

        def _boom(*args, **kwargs):
            raise AssertionError("заглушка 1С не должна создавать HTTP-клиент")

        monkeypatch.setattr(httpx, "AsyncClient", _boom)
        client = StubOneCClient()
        with pytest.raises(OneCNotConfiguredError):
            await client.export_orders(OrderExportRequest())
        await client.aclose()

    async def test_aclose_is_safe(self):
        assert await StubOneCClient().aclose() is None

    def test_default_message_template(self):
        """Тексты ошибок — из константы, а не склеены по месту."""
        rendered = NOT_CONFIGURED_MESSAGE.format(reason="R", action="A", hint="H")
        assert rendered == "Интеграция с 1С не настроена: R. Операция «A» не выполнена. H"


# ---------- Фабрика: выбор реализации по настройкам ----------
def _cfg(**overrides):
    """Настройки 1С как объект без чтения .env (без БД и окружения)."""
    base = {
        "integration_1c_enabled": False,
        "integration_1c_base_url": "",
        "integration_1c_timeout_sec": 10.0,
        "integration_1c_token": "",
    }
    base.update(overrides)
    return type("Cfg", (), base)()


class TestFactory:
    def test_unconfigured_returns_stub(self):
        client = create_one_c_client(_cfg())
        assert isinstance(client, StubOneCClient)
        assert client.configured is False
        assert client.transport == "stub"

    def test_disabled_flag_returns_stub(self):
        """Флаг выключателя важнее заполненного URL: стенд без доступа к 1С."""
        client = create_one_c_client(_cfg(integration_1c_base_url="https://1c.example.by"))
        assert isinstance(client, StubOneCClient)
        assert client.reason.startswith("не задано INTEGRATION_1C_ENABLED=true")
        assert missing_outbound_settings(_cfg()) == [
            "INTEGRATION_1C_ENABLED=true",
            "INTEGRATION_1C_BASE_URL",
        ]

    def test_configured_returns_http_client_with_timeout(self):
        client = create_one_c_client(
            _cfg(
                integration_1c_enabled=True,
                integration_1c_base_url="https://1c.example.by/",
                integration_1c_timeout_sec=3.5,
                integration_1c_token=TOKEN,
            )
        )
        assert isinstance(client, HttpOneCClient)
        assert client.configured is True
        assert client.base_url == "https://1c.example.by"  # без хвостового слэша
        assert client.timeout_sec == 3.5

    def test_zero_timeout_is_raised_to_minimum(self):
        """timeout=0 у httpx = «ждать вечно» — в обмене с 1С это зависание."""
        client = create_one_c_client(
            _cfg(
                integration_1c_enabled=True,
                integration_1c_base_url="https://1c.example.by",
                integration_1c_timeout_sec=0,
            )
        )
        assert client.timeout_sec > 0

    def test_broken_settings_fall_back_to_stub(self):
        """Фабрика не бросает исключений — даже с испорченными настройками."""

        class Broken:
            @property
            def integration_1c_enabled(self):
                raise RuntimeError("настройки сломаны")

        client = create_one_c_client(Broken())
        assert isinstance(client, StubOneCClient)
        assert "не удалось построить клиент 1С" in client.reason

    def test_missing_settings_listing(self):
        cfg = _cfg()
        assert missing_outbound_settings(cfg) == [
            "INTEGRATION_1C_ENABLED=true",
            "INTEGRATION_1C_BASE_URL",
        ]
        assert "не заданы" in describe_one_c_state(cfg)

        cfg_on = _cfg(
            integration_1c_enabled=True, integration_1c_base_url="https://1c.example.by"
        )
        assert missing_outbound_settings(cfg_on) == []
        assert describe_one_c_state(cfg_on).startswith("настроено")

    def test_singleton_is_cached_and_resettable(self):
        reset_one_c_client()
        first = get_one_c_client()
        assert get_one_c_client() is first
        assert isinstance(first, OneCClient)  # реализует протокол
        reset_one_c_client()
        assert get_one_c_client() is not first
        reset_one_c_client()


# ---------- Приложение стартует и содержит ручки 1С ----------
class TestAppWiring:
    def test_app_state_has_one_c_client(self):
        """main.py больше не «молчит» про 1С: клиент в состоянии приложения."""
        assert isinstance(app.state.one_c_client, OneCClient)

    def test_router_registered_on_expected_prefix(self):
        """Контракт виден в OpenAPI — ручки не исчезли молча из схемы.

        В FastAPI 0.141 include ленивый, поэтому app.routes содержит
        '_IncludedRouter' без .path; проверяем схему, а не список роутов.
        """
        paths = set(app.openapi()["paths"])
        assert "/api/integrations/1c/orders/export" in paths
        assert "/api/integrations/1c/orders/status" in paths
        assert "/api/integrations/1c/prices/import" in paths
        assert "/api/integrations/1c/stock/import" in paths

    def test_openapi_documents_stub_status_codes(self):
        """1С должна видеть в схеме и 503, и 501 — иначе непонятно, что делать."""
        operations = app.openapi()["paths"]["/api/integrations/1c/orders/export"]["get"]
        assert {"401", "403", "501", "503"} <= set(operations["responses"])

    def test_settings_expose_helpers(self):
        assert settings.integration_1c_inbound_configured is bool(
            settings.integration_1c_token.strip()
        )
        assert isinstance(settings.integration_1c_ip_allowlist_list, list)


# ---------- HTTP-ручки §18.2 ----------
def _client(app_override=None):
    transport = httpx.ASGITransport(app=app_override or app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def configured_token(monkeypatch):
    """Включаем входящий токен; allowlist пуст — проверяем только токен."""
    monkeypatch.setattr(settings, "integration_1c_token", TOKEN)
    return TOKEN


class TestEndpointsWithoutConfiguration:
    """По умолчанию (пустой INTEGRATION_1C_TOKEN) ручки отвечают 503."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/integrations/1c/orders/export"),
            ("POST", "/api/integrations/1c/prices/import"),
            ("POST", "/api/integrations/1c/stock/import"),
            ("POST", "/api/integrations/1c/orders/status"),
        ],
    )
    async def test_returns_503_not_configured(self, monkeypatch, method, path):
        monkeypatch.setattr(settings, "integration_1c_token", "")
        async with _client() as client:
            resp = await client.request(
                method, path, headers={"X-Integration-Token": TOKEN}, json={}
            )
        assert resp.status_code == 503
        body = resp.json()
        assert "не настроена" in body["detail"]
        assert body["code"] == "ONE_C_NOT_CONFIGURED"
        assert body["schema_version"] == SCHEMA_VERSION


class TestEndpointsAuthorization:
    async def test_wrong_token_returns_401(self, configured_token):
        async with _client() as client:
            resp = await client.get(
                "/api/integrations/1c/orders/export",
                headers={"X-Integration-Token": "wrong"},
            )
        assert resp.status_code == 401
        assert resp.json()["code"] == "ONE_C_AUTH_FAILED"

    async def test_missing_token_returns_401(self, configured_token):
        async with _client() as client:
            resp = await client.get("/api/integrations/1c/orders/export")
        assert resp.status_code == 401

    async def test_ip_not_in_allowlist_returns_403(self, monkeypatch, configured_token):
        monkeypatch.setattr(settings, "integration_1c_ip_allowlist", "10.0.0.1,10.0.0.2")
        async with _client() as client:
            resp = await client.get(
                "/api/integrations/1c/orders/export",
                headers={"X-Integration-Token": configured_token},
            )
        assert resp.status_code == 403
        assert resp.json()["code"] == "ONE_C_IP_FORBIDDEN"
        assert "не входит в INTEGRATION_1C_IP_ALLOWLIST" in resp.json()["detail"]

    async def test_allowed_ip_passes_allowlist(self, monkeypatch, configured_token):
        # ASGITransport приходит с client host 127.0.0.1
        monkeypatch.setattr(settings, "integration_1c_ip_allowlist", "127.0.0.1,10.0.0.1")
        async with _client() as client:
            resp = await client.get(
                "/api/integrations/1c/orders/export",
                headers={"X-Integration-Token": configured_token},
            )
        # Дальше — штатная заглушка 501, а не 403: allowlist отработал.
        assert resp.status_code == 501

    async def test_comparison_is_constant_time(self, monkeypatch):
        """Токен сравнивается hmac.compare_digest, а не «==» (timing-атака)."""
        import hmac as hmac_lib

        seen = []
        original = hmac_lib.compare_digest

        def spy(a, b):
            seen.append((a, b))
            return original(a, b)

        monkeypatch.setattr(one_c_api.hmac, "compare_digest", spy)
        monkeypatch.setattr(settings, "integration_1c_token", TOKEN)
        async with _client() as client:
            await client.get(
                "/api/integrations/1c/orders/export",
                headers={"X-Integration-Token": "wrong"},
            )
        assert seen and seen[0] == ("wrong", TOKEN)


class TestStubEndpoints:
    """Токен есть, обмен не настроен → 501 + schema_version (§18.2)."""

    async def test_export_orders_returns_501(self, configured_token):
        async with _client() as client:
            resp = await client.get(
                "/api/integrations/1c/orders/export",
                headers={"X-Integration-Token": configured_token},
            )
        assert resp.status_code == 501
        body = resp.json()
        assert body["schema_version"] == SCHEMA_VERSION
        assert body["code"] == "ONE_C_NOT_IMPLEMENTED"
        assert "не реализована" in body["detail"]
        # Причина отказа заглушки сохраняется в ответе — оператор видит, что задать
        assert "INTEGRATION_1C_ENABLED=true" in body["detail"]

    async def test_prices_import_validates_body_then_501(self, configured_token):
        """Некорректное тело → 422 (1С может исправить и повторить), не 501."""
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/prices/import",
                headers={"X-Integration-Token": configured_token},
                json={"date": "2026-01-01T00:00:00Z", "items": []},
            )
        assert resp.status_code == 422

        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/prices/import",
                headers={"X-Integration-Token": configured_token},
                json={
                    "date": "2026-01-01T00:00:00Z",
                    "items": [
                        {
                            "product": {"guid": "GUID-1", "sku": "SKU-1"},
                            "price": "12.50",
                            "currency": "BYN",
                        }
                    ],
                },
            )
        assert resp.status_code == 501
        assert resp.json()["received"] == 1

    async def test_stock_import_returns_501(self, configured_token):
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/stock/import",
                headers={"X-Integration-Token": configured_token},
                json={
                    "date": "2026-01-01T00:00:00Z",
                    "items": [
                        {
                            "product": {"guid": "GUID-1"},
                            "warehouse": {"id": "WH-1", "name": "Основной"},
                            "quantity": 10,
                            "reserved": 3,
                        }
                    ],
                },
            )
        assert resp.status_code == 501
        assert resp.json()["received"] == 1

    async def test_order_status_returns_501(self, configured_token):
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/orders/status",
                headers={"X-Integration-Token": configured_token},
                json={
                    "stamp": {"date": "2026-01-01T00:00:00Z"},
                    "external_id": "УТ-000012",
                    "status": "shipped",
                    "changed_at": "2026-01-02T10:00:00Z",
                },
            )
        assert resp.status_code == 501
        assert "СтатусЗаказа" in resp.json()["detail"]


class TestAuthPrecedesBodyValidation:
    """1С без прав не должна получать разбор своего же тела (§18, §11)."""

    async def test_unauthorized_bad_body_returns_503_not_422(self, monkeypatch):
        """Пустой токен → 503 даже при заведомо некорректном теле."""
        monkeypatch.setattr(settings, "integration_1c_token", "")
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/prices/import",
                headers={"X-Integration-Token": TOKEN},
                json={"items": []},
            )
        assert resp.status_code == 503

    async def test_wrong_token_bad_body_returns_401_not_422(self, configured_token):
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/orders/status",
                headers={"X-Integration-Token": "wrong"},
                json={"garbage": True},
            )
        assert resp.status_code == 401

    async def test_bad_json_returns_400(self, configured_token):
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/stock/import",
                headers={"X-Integration-Token": configured_token},
                content=b"<html>error</html>",
            )
        assert resp.status_code == 400
        assert resp.json()["code"] == "ONE_C_BAD_JSON"

    async def test_empty_body_returns_400(self, configured_token):
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/prices/import",
                headers={"X-Integration-Token": configured_token},
                content=b"",
            )
        assert resp.status_code == 400
        assert resp.json()["code"] == "ONE_C_EMPTY_BODY"

    async def test_schema_error_lists_fields(self, configured_token):
        """422 с деталями полей — 1С может поправить документ и повторить."""
        async with _client() as client:
            resp = await client.post(
                "/api/integrations/1c/prices/import",
                headers={"X-Integration-Token": configured_token},
                json={
                    "date": "2026-01-01T00:00:00Z",
                    "items": [{"product": {}, "price": "-1"}],
                },
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "ONE_C_SCHEMA_ERROR"
        assert body["errors"], "нужны детали полей для 1С"


# ---------- Реальный клиент: контракт и ошибки без сети ----------
def _http_client(handler, **kwargs):
    """HttpOneCClient поверх MockTransport: ни одного реального соединения."""
    return HttpOneCClient(
        base_url="https://1c.example.by",
        timeout_sec=1.0,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://1c.example.by"
        ),
        **kwargs,
    )


ORDER_DOC = {
    "stamp": {"date": "2026-01-01T00:00:00Z"},
    "external_id": "УТ-000012",
    "customer": {"inn": "7700000000"},
    "total": "12.50",
    "lines": [
        {
            "product": {"guid": "GUID-1", "sku": "SKU-1"},
            "quantity": "2",
            "price": "6.25",
            "currency": "BYN",
        }
    ],
}


class TestHttpClientContract:
    async def test_timeout_maps_to_transport_error(self):
        def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)

        client = _http_client(handler)
        with pytest.raises(OneCTransportError) as exc_info:
            await client.export_orders(OrderExportRequest())
        assert "1С" in str(exc_info.value)

    async def test_network_error_maps_to_transport_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        client = _http_client(handler)
        with pytest.raises(OneCTransportError):
            await client.push_order_status(
                OrderStatusRequest(
                    change=OrderStatusChange.model_validate(
                        {
                            "stamp": {"date": "2026-01-01T00:00:00Z"},
                            "external_id": "УТ-1",
                            "status": "shipped",
                            "changed_at": "2026-01-02T10:00:00Z",
                        }
                    )
                )
            )

    async def test_auth_rejection_maps_to_auth_error(self):
        client = _http_client(lambda request: httpx.Response(401, json={}))
        with pytest.raises(OneCAuthError):
            await client.export_orders(OrderExportRequest())

    async def test_server_error_maps_to_response_error(self):
        client = _http_client(lambda request: httpx.Response(500, json={}))
        with pytest.raises(OneCResponseError):
            await client.export_orders(OrderExportRequest())

    async def test_non_json_maps_to_response_error(self):
        client = _http_client(lambda request: httpx.Response(200, text="<html>500</html>"))
        with pytest.raises(OneCResponseError) as exc_info:
            await client.export_orders(OrderExportRequest())
        assert "не-JSON" in str(exc_info.value)

    async def test_orders_are_parsed_into_commerceml(self):
        payload = {"schema_version": "2.10", "orders": [ORDER_DOC]}
        client = _http_client(lambda request: httpx.Response(200, json=payload))
        result = await client.export_orders(OrderExportRequest())

        assert isinstance(result, OrderExportResult)
        assert len(result.orders) == 1
        assert str(result.orders[0].external_id) == "УТ-000012"

    async def test_status_push_parses_answer(self):
        def handler(request):
            assert request.url.path == "/orders/status"
            return httpx.Response(200, json={"external_id": "УТ-1", "accepted": True})

        client = _http_client(handler)
        result = await client.push_order_status(
            OrderStatusRequest(
                change=OrderStatusChange.model_validate(
                    {
                        "stamp": {"date": "2026-01-01T00:00:00Z"},
                        "external_id": "УТ-1",
                        "status": "shipped",
                        "changed_at": "2026-01-02T10:00:00Z",
                    }
                )
            )
        )
        assert result.accepted is True
        assert result.external_id == "УТ-1"

    async def test_client_does_not_leak_connection_on_aclose(self):
        injected = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        client = HttpOneCClient(base_url="https://1c.example.by", client=injected)
        await client.aclose()
        assert injected.is_closed is False  # чужой клиент закрывать нельзя

    async def test_configured_and_describe(self):
        client = HttpOneCClient(base_url="https://1c.example.by", timeout_sec=7)
        assert client.configured is True
        assert "timeout=7.0s" in client.describe()
        # Соединение не создаётся в конструкторе — неверный URL не роняет старт
        assert client._client is None


class TestResultModels:
    def test_export_result_defaults(self):
        result = OrderExportResult(orders=[])
        assert result.schema_version == SCHEMA_VERSION
        assert result.exported_at is not None

    def test_status_result_defaults(self):
        result = OrderStatusResult(external_id="УТ-1", accepted=True)
        assert result.accepted is True
        assert result.schema_version == SCHEMA_VERSION