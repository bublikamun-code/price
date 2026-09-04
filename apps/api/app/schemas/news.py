"""DTO новостейной ленты. См. ARCHITECTURE_PLAN.md §6."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import NewsType
from app.schemas import MetaPage


class NewsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    type: str
    image_url: str | None = None
    published_at: datetime
    is_active: bool = True


class NewsPage(BaseModel):
    data: list[NewsRead]
    meta: MetaPage


class NewsCreate(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    type: NewsType
    image_url: str | None = None
    published_at: datetime | None = None
    is_active: bool = True


class NewsUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    type: NewsType | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    is_active: bool | None = None
