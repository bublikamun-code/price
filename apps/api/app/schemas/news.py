"""DTO новостейной ленты. См. ARCHITECTURE_PLAN.md §6."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import MetaPage


class NewsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    type: str
    image_url: str | None = None
    published_at: datetime


class NewsPage(BaseModel):
    data: list[NewsRead]
    meta: MetaPage
