"""Problem Details transport for API v2.

Handlers are registered globally but branch on the request path. This keeps
legacy v1 envelopes byte-for-byte compatible while allowing v2 to use RFC 9457
for domain, HTTP, validation and unhandled errors.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.v2.common import ProblemDetails, ProblemFieldError

PROBLEM_BASE_URL = "https://priceweb.local/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"
_V2_PREFIX = "/api/v2"


class V2ProblemError(Exception):
    """Domain error that already has a stable v2 code and HTTP status."""

    def __init__(
        self,
        *,
        code: str,
        status: int,
        title: str,
        detail: str,
        errors: list[ProblemFieldError] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.errors = errors or []
        super().__init__(detail)


def is_v2_request(request: Request) -> bool:
    return request.url.path.startswith(f"{_V2_PREFIX}/") or request.url.path == _V2_PREFIX


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


def parse_if_match(value: str | None) -> int:
    """Parse a v2 strong or weak integer entity tag.

    Only the explicitly supported forms ``3``, ``\"3\"`` and ``W/\"3\"``
    are accepted. A missing or malformed header is a domain problem, not a
    FastAPI validation error, so v2 keeps its stable error envelope.
    """
    if value is None:
        raise V2ProblemError(
            code="INVALID_IF_MATCH",
            status=400,
            title="Некорректный If-Match",
            detail="If-Match обязателен и должен содержать версию ресурса",
        )
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    try:
        version = int(normalized)
    except (TypeError, ValueError) as exc:
        raise V2ProblemError(
            code="INVALID_IF_MATCH",
            status=400,
            title="Некорректный If-Match",
            detail="If-Match должен содержать целую версию ресурса",
        ) from exc
    if version < 1 or str(version) != normalized:
        raise V2ProblemError(
            code="INVALID_IF_MATCH",
            status=400,
            title="Некорректный If-Match",
            detail="If-Match должен содержать положительную целую версию ресурса",
        )
    return version


def problem_type(code: str) -> str:
    return f"{PROBLEM_BASE_URL}{code.lower().replace('_', '-')}"


def problem_response(
    request: Request,
    *,
    code: str,
    status: int,
    title: str,
    detail: str,
    errors: list[ProblemFieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ProblemDetails(
        type=problem_type(code),
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id_for(request),
        errors=errors or [],
    )
    response_headers = {"Content-Type": PROBLEM_MEDIA_TYPE}
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status,
        content=payload.model_dump(mode="json", by_alias=True),
        headers=response_headers,
    )


def problem_responses(statuses: dict[int, str]) -> dict[int, dict[str, Any]]:
    """Describe the same v2 Problem Details response for every route status."""
    return {
        status_code: {
            "model": ProblemDetails,
            "description": description,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for status_code, description in statuses.items()
    }


def from_domain_error(request: Request, exc: V2ProblemError) -> JSONResponse:
    return problem_response(
        request,
        code=exc.code,
        status=exc.status,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
    )


_HTTP_PROBLEMS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Некорректный запрос"),
    401: ("AUTHENTICATION_REQUIRED", "Требуется авторизация"),
    403: ("PERMISSION_DENIED", "Недостаточно прав"),
    404: ("RESOURCE_NOT_FOUND", "Ресурс не найден"),
    405: ("METHOD_NOT_ALLOWED", "Метод не поддерживается"),
    409: ("CONFLICT", "Конфликт состояния"),
    413: ("PAYLOAD_TOO_LARGE", "Слишком большой запрос"),
    429: ("RATE_LIMITED", "Слишком много запросов"),
}


def _http_problem(
    exc: HTTPException | StarletteHTTPException,
) -> tuple[str, str, str, int, dict[str, str]]:
    status = int(exc.status_code)
    code, title = _HTTP_PROBLEMS.get(status, ("INTERNAL_ERROR", "Ошибка сервера"))
    detail = exc.detail if isinstance(exc.detail, str) else title
    headers = dict(exc.headers or {})
    return code, title, detail, status, headers


def http_problem_response(
    request: Request,
    exc: HTTPException | StarletteHTTPException,
) -> JSONResponse:
    code, title, detail, status, headers = _http_problem(exc)
    return problem_response(
        request,
        code=code,
        status=status,
        title=title,
        detail=detail,
        headers=headers,
    )


def validation_problem_response(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    raw_errors = exc.errors()
    if is_v2_request(request) and any(
        error.get("type") == "missing"
        and "If-Match" in error.get("loc", ())
        for error in raw_errors
    ):
        return problem_response(
            request,
            code="INVALID_IF_MATCH",
            status=400,
            title="Некорректный If-Match",
            detail="If-Match обязателен и должен содержать версию ресурса",
        )
    errors: list[ProblemFieldError] = []
    for error in raw_errors:
        location = ".".join(
            str(part)
            for part in error.get("loc", ())
            if part not in {"body", "path"}
        )
        errors.append(
            ProblemFieldError(
                field=location or "request",
                code=str(error.get("type", "INVALID_VALUE")).upper(),
                message=str(error.get("msg", "Некорректное значение")),
            )
        )
    return problem_response(
        request,
        code="VALIDATION_ERROR",
        status=422,
        title="Ошибка валидации",
        detail="Один или несколько параметров запроса некорректны",
        errors=errors,
    )


__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "V2ProblemError",
    "from_domain_error",
    "http_problem_response",
    "is_v2_request",
    "parse_if_match",
    "problem_response",
    "problem_responses",
    "request_id_for",
    "validation_problem_response",
]
