"""Pydantic DTO.

См. ARCHITECTURE_PLAN.md §6 — единый envelope ответа.
"""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[Any] | dict[str, Any] | None = None


class APIError(BaseModel):
    error: ErrorResponse


class MetaPage(BaseModel):
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=200)
    total: int = Field(ge=0)


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: MetaPage


class OK(BaseModel):
    """Простой ответ на мутации без данных."""
    ok: bool = True
