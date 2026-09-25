"""Signed, opaque cursor primitives for API v2 list endpoints.

Cursors are intentionally not offset tokens.  The payload binds the keyset
value and stable UUID tie-breaker to the resource, sort and normalized filter,
then authenticates the complete payload with the application secret.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from typing import Any

from app.core.config import settings

_CURSOR_VERSION = 1


class InvalidCursorError(ValueError):
    """Raised when a cursor is malformed, tampered with, or out of context."""


def filter_signature(*parts: str | None) -> str:
    """Return a stable, non-reversible signature for list filter inputs."""
    canonical = json.dumps(
        [part.strip() if part is not None else None for part in parts],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > 4096:
        raise InvalidCursorError
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidCursorError from exc


def _sign(encoded_payload: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def encode_cursor(
    *,
    resource: str,
    sort: str,
    filter_sig: str,
    value: str,
    item_id: uuid.UUID,
) -> str:
    payload: dict[str, Any] = {
        "v": _CURSOR_VERSION,
        "resource": resource,
        "sort": sort,
        "filter": filter_sig,
        "value": value,
        "id": str(item_id),
    }
    encoded_payload = _b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def decode_cursor(
    value: str,
    *,
    resource: str,
    sort: str,
    filter_sig: str,
) -> dict[str, str]:
    """Decode and authenticate a cursor for the current request context."""
    try:
        encoded_payload, signature = value.split(".", 1)
    except (AttributeError, ValueError) as exc:
        raise InvalidCursorError from exc
    expected_signature = _sign(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidCursorError
    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise InvalidCursorError from exc
    if not isinstance(payload, dict):
        raise InvalidCursorError
    if (
        payload.get("v") != _CURSOR_VERSION
        or payload.get("resource") != resource
        or payload.get("sort") != sort
        or payload.get("filter") != filter_sig
        or not isinstance(payload.get("value"), str)
        or not isinstance(payload.get("id"), str)
    ):
        raise InvalidCursorError
    try:
        uuid.UUID(payload["id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidCursorError from exc
    return {
        "resource": resource,
        "sort": sort,
        "filter": filter_sig,
        "value": payload["value"],
        "id": payload["id"],
    }


__all__ = ["InvalidCursorError", "decode_cursor", "encode_cursor", "filter_signature"]
