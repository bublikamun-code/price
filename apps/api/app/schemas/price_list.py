"""DTO для импорта прайс-листов. См. ARCHITECTURE_PLAN.md §6 (manager/prices), §7."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import ImportMode, PriceListVersionStatus
from app.schemas import MetaPage


class ImportUploadOut(BaseModel):
    """Ответ на ``POST /manager/prices/import`` — принятая в обработку версия."""

    version_id: uuid.UUID
    status: PriceListVersionStatus
    filename: str
    created_at: datetime


class PriceListVersionRead(BaseModel):
    """Карточка версии импорта (статус, счётчики, курс, отчёт ошибок)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    import_mode: ImportMode
    status: PriceListVersionStatus
    rows_total: int
    rows_ok: int
    rows_error: int
    base_currency: str
    rate_to_byn: Decimal
    rate_source: str | None
    error_log_key: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    uploaded_by: uuid.UUID | None

    # Аудит отката версии (§16 п.14): заполнено — версия уже откачена.
    rolled_back_at: datetime | None = None
    rolled_back_by: uuid.UUID | None = None


class RollbackOut(BaseModel):
    """Ответ на ``POST /manager/prices/versions/{id}/rollback`` (§16 п.14).

    ``restored`` — товары, возвращённые к ценам последнего снапшота до версии;
    ``archived`` — товары, впервые появившиеся в версии (soft-delete).
    """

    version: PriceListVersionRead
    restored: int
    archived: int


class PriceListVersionPage(BaseModel):
    data: list[PriceListVersionRead]
    meta: MetaPage
