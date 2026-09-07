"""DTO администрирования: менеджеры (/api/v1/admin/managers). См. §6, §11.

Контракт совпадает с apps/web/pages/manager/admin.vue 1-в-1:
  * GET  /admin/managers           → плоский list[AdminManagerOut] (без конверта);
  * POST /admin/managers           → 201 AdminManagerCreateOut {user, temp_password};
  * PATCH /admin/managers/{id}     → AdminManagerOut (is_active/full_name/phone).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class AdminManagerIn(BaseModel):
    """Создание менеджера: email/ФИО + опциональный телефон.

    Пароль не приходит — temp-пароль генерирует сервис (паттерн §16 п.19).
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = None


class AdminManagerPatchIn(BaseModel):
    """Частичное обновление: правка профиля и/или блокировка/разблокировка."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = None
    is_active: bool | None = None


class AdminManagerOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    is_active: bool
    created_at: datetime


class AdminManagerCreateOut(BaseModel):
    user: AdminManagerOut
    temp_password: str
