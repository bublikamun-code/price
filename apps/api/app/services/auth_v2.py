"""Adapters that project the transport-agnostic AuthService onto the v2 contract.

AuthService не знает про cookie и работает с refresh-токеном как со строкой —
этого достаточно, чтобы нативный клиент получил токены в теле ответа, а не в
httpOnly-cookie (docs/NATIVE_API_CONTRACT.md §4). Здесь живёт только перевод
доменных ошибок в коды Problem Details; бизнес-логика не дублируется.
"""
from __future__ import annotations

from app.api.v2.errors import V2ProblemError
from app.schemas.auth import TokenPair
from app.services.auth import AuthError


def to_problem(exc: AuthError) -> V2ProblemError:
    """Отображает доменную ошибку аутентификации в v2 Problem Details."""
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=str(exc),
    )


def grant_tokens(token_pair: TokenPair) -> tuple[str, str, int]:
    """(access, refresh, expires_in) — refresh берётся из TokenPair, а не из
    сериализованного тела: v1-схема исключает его из JSON через Field(exclude)."""
    return token_pair.access_token, token_pair.refresh_token, token_pair.expires_in


__all__ = ["grant_tokens", "to_problem"]
