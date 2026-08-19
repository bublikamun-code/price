"""DTO журнала аудита (§5, §6, §16 п.19)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas import MetaPage


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    created_at: datetime


class AuditPage(BaseModel):
    data: list[AuditRead]
    meta: MetaPage
