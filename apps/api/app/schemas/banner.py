"""DTO баннеров главной страницы. См. ARCHITECTURE_PLAN.md §6."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BannerLinkType, BannerPosition


class BannerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    subtitle: str | None = None
    image_key: str | None = None
    link_type: BannerLinkType
    link_value: str | None = None
    position: BannerPosition
    sort: int
    is_active: bool = True


class BannerCreate(BaseModel):
    title: str = Field(min_length=1)
    subtitle: str | None = None
    image_key: str | None = None
    link_type: BannerLinkType = BannerLinkType.NONE
    link_value: str | None = None
    position: BannerPosition
    sort: int = 0
    is_active: bool = True


class BannerUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    subtitle: str | None = None
    image_key: str | None = None
    link_type: BannerLinkType | None = None
    link_value: str | None = None
    position: BannerPosition | None = None
    sort: int | None = None
    is_active: bool | None = None
