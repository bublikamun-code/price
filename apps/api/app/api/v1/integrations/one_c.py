"""Эндпоинты интеграции с 1С — заглушки, спроектированные по контракту (§18.2).

Четыре ручки §18.2 под subroute ``/api/integrations/1c`` (отдельный include на
``app``, вне ``/api/v1``). Обмен с 1С в MVP **не реализован** (§18.1), поэтому
ручки не делают вид, что работают: они валидируют вход по контракту CommerceML
и отвечают кодом, который честно говорит о состоянии интеграции.

Поведение (совпадает с решением п.24 в §15/§18.2):

======  ==========================================================  ======
Код    Когда                                                       Ответ
======  ==========================================================  ======
``400`` тело не-JSON / пустое / не объект                          ошибка формата
``401`` токен не совпал с ``INTEGRATION_1C_TOKEN``                  Unauthorized
``403`` IP 1С не в allowlist                                        Forbidden
``422`` тело не сошлось с контрактом CommerceML (после 401/403/503)  детали полей
``501`` контракт спроектирован, обмен не реализован (MVP)          + schema_version
``503`` интеграция не настроена (пустой токен / заглушка)          «не настроено»
======  ==========================================================  ======

Порядок проверок именно такой: **сначала доступ, потом разбор тела**. FastAPI
валидирует тело эндпоинта до входа в функцию, поэтому тело читается вручную
(``_json_body`` + ``_validated``) — иначе «не настроена»/«нет доступа» было бы
невозможно сообщить раньше 422, а неавторизованный отправитель получал бы
подробности контракта и заставлял нас разбирать его данные.

Авторизация (§18.1): статический токен в заголовке ``X-Integration-Token``
сравнивается constant-time, дополнительно проверяется IP-allowlist.
Все попытки логируются structlog; ``audit_log`` на заглушках не пишется —
по решению п.24 exchange-операции фиксируются при реальной реализации.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime
from typing import TypeVar

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.one_c import (
    OneCClient,
    OneCError,
    OneCNotConfiguredError,
    OrderExportRequest,
    OrderStatusRequest,
    create_one_c_client,
)
from app.schemas.commerceml import (
    SCHEMA_VERSION,
    OrderStatusChange,
    PriceDocument,
    StockDocument,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

#: Константа вместо status.HTTP_422_UNPROCESSABLE_ENTITY: имя переименовано в
#: Starlette 1.7, а литерл переживёт любую версию.
HTTP_422 = 422

log = get_logger("app.api.integrations.one_c")

router = APIRouter(prefix="/integrations/1c", tags=["integrations-1c"])

__all__ = ["STUB_DETAILS", "router"]

#: Тексты 501 — ручка спроектирована, но обмен не реализован (§18).
STUB_DETAILS = {
    "orders/export": (
        "Выгрузка заказов в 1С не реализована (Этап 11.5, §18). "
        "Контракт: CommerceML 2.10, параметры ?since= и ?schema_version=."
    ),
    "prices/import": (
        "Приём прайса из 1С не реализован (Этап 11.5, §18). "
        "Контракт: документ ПрайсЛист в формате CommerceML 2.10."
    ),
    "stock/import": (
        "Обновление складских остатков из 1С не реализовано (Этап 11.5, §18). "
        "Контракт: документ ОстаткиТоваров в формате CommerceML 2.10."
    ),
    "orders/status": (
        "Возврат статуса заказа из 1С не реализован (Этап 11.5, §18). "
        "Контракт: документ СтатусЗаказа в формате CommerceML 2.10."
    ),
}


# ---------- Вспомогательное ----------
def _client_ip(request: Request) -> str:
    """IP клиента; за обратным прокси — первый адрес X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _one_c_client(request: Request) -> OneCClient:
    """Клиент из состояния приложения; при отсутствии — собираем по настройкам.

    ``app.state.one_c_client`` выставляется в ``main.py`` при старте. Второй
    путь нужен для тестов и для случая, когда состояние не выставлено: клиент
    в любом случае есть, «интеграция» не должна ронять обработчик запроса.
    """
    client = getattr(request.app.state, "one_c_client", None)
    if client is None:
        client = create_one_c_client(settings)
        request.app.state.one_c_client = client
    return client


def _payload(detail: str, **extra: object) -> dict[str, object]:
    """Тело ответа 1С: обязательный detail + schema_version (§18.2)."""
    return {"detail": detail, "schema_version": SCHEMA_VERSION, **extra}


def _not_implemented(
    operation: str, exc: OneCNotConfiguredError, received: int | None = None
) -> JSONResponse:
    """501 «контракт есть, реализации нет» — тело сохраняет причину отказа.

    ``received`` (для приёма данных от 1С) показывает, сколько позиций дошло
    необработанными: 1С так понимает, что вызов дошёл и данные не потеряны,
    повторять его нужно будет после включения интеграции.
    """
    detail = f"{STUB_DETAILS[operation]} Причина: {exc}"
    log.info("one_c.stub_operation", operation=operation)
    extra: dict[str, object] = {"code": "ONE_C_NOT_IMPLEMENTED", "transport": "stub"}
    if received is not None:
        extra["received"] = received
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=_payload(detail, **extra),
    )


def _stub_reason(client: OneCClient) -> OneCNotConfiguredError:
    """Причина «не настроено» из клиента-заглушки (у HTTP-клиента её нет)."""
    reason = getattr(client, "reason", "интеграция с 1С не настроена")
    return OneCNotConfiguredError(
        f"Интеграция с 1С не настроена: {reason}. "
        "Задайте INTEGRATION_1C_ENABLED=true и INTEGRATION_1C_BASE_URL."
    )


def _client_error(exc: OneCError) -> JSONResponse:
    """Ошибка реального обмена (таймаут, отказ 1С) — 502, детали 1С наружу."""
    log.error("one_c.client_error", code=exc.code, error=str(exc))
    return JSONResponse(
        status_code=exc.http_status, content=_payload(str(exc), code=exc.code)
    )


def _authorize(request: Request, token: str | None) -> JSONResponse | None:
    """Проверка прав 1С: настроен ли токен, совпадает ли, разрешён ли IP.

    ``None`` — запрос авторизован, иначе готовый ответ (401/403/503).
    """
    expected = settings.integration_1c_token
    if not expected.strip():
        # Не 401: 1С ещё не задали токен на нашей стороне — это состояние
        # стенда, а не отказ в доступе.
        log.warning("one_c.inbound_not_configured", ip=_client_ip(request))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_payload(
                "Интеграция с 1С не настроена: не задан INTEGRATION_1C_TOKEN — "
                "входящие запросы 1С не принимаются. Задайте переменную в .env "
                "и перезапустите api.",
                code="ONE_C_NOT_CONFIGURED",
            ),
        )

    supplied = token or ""
    if not hmac.compare_digest(supplied, expected):
        log.warning("one_c.auth_failed", ip=_client_ip(request), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_payload(
                "Неверный X-Integration-Token", code="ONE_C_AUTH_FAILED"
            ),
        )

    allowlist = settings.integration_1c_ip_allowlist_list
    if allowlist:
        ip = _client_ip(request)
        if ip not in allowlist:
            log.warning("one_c.ip_forbidden", ip=ip, path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content=_payload(
                    f"IP {ip or 'неизвестен'} не входит в INTEGRATION_1C_IP_ALLOWLIST",
                    code="ONE_C_IP_FORBIDDEN",
                ),
            )
    return None


async def _json_body(request: Request) -> tuple[dict[str, object] | None, JSONResponse | None]:
    """Прочитать JSON-тело входящего запроса 1С (после авторизации!).

    Тело читается вручную, а не через параметр модели, намеренно: FastAPI
    валидирует тело эндпоинта **до** входа в функцию, поэтому «не настроена»
    (503) и «нет доступа» (401/403) нельзя было бы сообщить раньше 422 на
    некорректном теле. Порядок важен и по существу: неавторизованный отправитель
    не должен ни получать подробностей контракта, ни заставлять нас разбирать
    его данные.
    """
    raw = await request.body()
    if not raw:
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_payload("Пустое тело запроса", code="ONE_C_EMPTY_BODY"),
        )
    try:
        payload = json.loads(raw)
    except ValueError:
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_payload("Тело запроса не является JSON", code="ONE_C_BAD_JSON"),
        )
    if not isinstance(payload, dict):
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_payload(
                "Ожидался JSON-объект документа CommerceML", code="ONE_C_BAD_JSON"
            ),
        )
    return payload, None


def _validated(model: type[ModelT], payload: dict[str, object]) -> ModelT | JSONResponse:
    """Проверить документ по модели CommerceML; ошибки — 422 в деталях.

    422, а не 400: контракт известен, данные не сошлись — 1С может поправить
    документ и повторить вызов.
    """
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        # Только loc/msg/type: сырой errors() может содержать несериализуемые
        # объекты (ctx с ValueError), и ответ 1С превратился бы в 500.
        details = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=HTTP_422,
            content=_payload(
                "Тело не соответствует контракту CommerceML 2.10",
                code="ONE_C_SCHEMA_ERROR",
                errors=details,
            ),
        )


#: Ошибки, документированные в OpenAPI для всех ручек §18.2.
_DOC_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"description": "Тело не-JSON или не объект документа"},
    401: {"description": "Неверный X-Integration-Token"},
    403: {"description": "IP вне INTEGRATION_1C_IP_ALLOWLIST"},
    422: {"description": "Тело не соответствует контракту CommerceML"},
    501: {"description": "Обмен с 1С не реализован (§18), схема обмена приложена"},
    503: {"description": "Интеграция с 1С не настроена"},
}


# ---------- Эндпоинты §18.2 ----------
@router.get("/orders/export", responses=_DOC_RESPONSES)
async def export_orders(
    request: Request,
    since: datetime | None = None,
    schema_version: str = SCHEMA_VERSION,
    x_integration_token: str | None = Header(default=None, alias="X-Integration-Token"),
) -> JSONResponse:
    """Выгрузка новых/изменённых заказов в 1С (``?since=``).

    Заглушка: контракт запроса (CommerceML-документы заказа) и параметры уже
    зафиксированы, обмен не реализован (§18.2).
    """
    if (denied := _authorize(request, x_integration_token)) is not None:
        return denied
    client = _one_c_client(request)
    if not client.configured:
        return _not_implemented("orders/export", _stub_reason(client))
    try:
        result = await client.export_orders(
            OrderExportRequest(since=since, schema_version=schema_version)
        )
    except OneCNotConfiguredError as exc:
        return _not_implemented("orders/export", exc)
    except OneCError as exc:
        return _client_error(exc)
    return JSONResponse(
        content=_payload(
            f"Выгружено заказов: {len(result.orders)}",
            schema_version=result.schema_version,
        )
    )


@router.post("/prices/import", responses=_DOC_RESPONSES)
async def import_prices(
    request: Request,
    x_integration_token: str | None = Header(default=None, alias="X-Integration-Token"),
) -> JSONResponse:
    """Приём прайса из 1С вместо ручного CSV.

    Тело — документ ``ПрайсЛист`` (CommerceML 2.10). Проверяется **после**
    авторизации: несоответствие контракту даёт 422 с деталями — 1С может
    исправить данные и повторить.
    """
    if (denied := _authorize(request, x_integration_token)) is not None:
        return denied
    payload, bad_request = await _json_body(request)
    if bad_request is not None:
        return bad_request
    document = _validated(PriceDocument, payload or {})
    if isinstance(document, JSONResponse):
        return document
    log.info("one_c.prices_import_received", items=len(document.items))
    client = _one_c_client(request)
    if not client.configured:
        return _not_implemented("prices/import", _stub_reason(client), len(document.items))
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=_payload(
            STUB_DETAILS["prices/import"],
            code="ONE_C_NOT_IMPLEMENTED",
            received=len(document.items),
        ),
    )


@router.post("/stock/import", responses=_DOC_RESPONSES)
async def import_stock(
    request: Request,
    x_integration_token: str | None = Header(default=None, alias="X-Integration-Token"),
) -> JSONResponse:
    """Обновление складских статусов из 1С (остатки).

    Тело — документ ``ОстаткиТоваров`` (CommerceML 2.10).
    """
    if (denied := _authorize(request, x_integration_token)) is not None:
        return denied
    payload, bad_request = await _json_body(request)
    if bad_request is not None:
        return bad_request
    document = _validated(StockDocument, payload or {})
    if isinstance(document, JSONResponse):
        return document
    log.info("one_c.stock_import_received", items=len(document.items))
    client = _one_c_client(request)
    if not client.configured:
        return _not_implemented("stock/import", _stub_reason(client), len(document.items))
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=_payload(
            STUB_DETAILS["stock/import"],
            code="ONE_C_NOT_IMPLEMENTED",
            received=len(document.items),
        ),
    )


@router.post("/orders/status", responses=_DOC_RESPONSES)
async def import_order_status(
    request: Request,
    x_integration_token: str | None = Header(default=None, alias="X-Integration-Token"),
) -> JSONResponse:
    """Возврат статуса заказа из 1С (отгружен и т.д.).

    Тело — документ ``СтатусЗаказа`` (CommerceML 2.10).
    """
    if (denied := _authorize(request, x_integration_token)) is not None:
        return denied
    payload, bad_request = await _json_body(request)
    if bad_request is not None:
        return bad_request
    change = _validated(OrderStatusChange, payload or {})
    if isinstance(change, JSONResponse):
        return change
    client = _one_c_client(request)
    if not client.configured:
        return _not_implemented("orders/status", _stub_reason(client))
    try:
        result = await client.push_order_status(OrderStatusRequest(change=change))
    except OneCNotConfiguredError as exc:
        return _not_implemented("orders/status", exc)
    except OneCError as exc:
        return _client_error(exc)
    return JSONResponse(
        content=_payload(
            f"Статус заказа {result.external_id} принят 1С",
            accepted=result.accepted,
            schema_version=result.schema_version,
        )
    )


__all__ = ["STUB_DETAILS", "router"]