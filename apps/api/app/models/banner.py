"""Баннеры главной страницы. См. ARCHITECTURE_PLAN.md §5."""
from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import BannerLinkType, BannerPosition, pg_enum


class Banner(Base, TimestampMixin, UUIDPrimaryKey):
    """Баннер главной страницы (промо / новинки).

    image_key — S3-ключ в photos-бакете; отдача через GET /api/v1/files/photo?key=.
    """
    __tablename__ = "banners"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    link_type: Mapped[BannerLinkType] = mapped_column(
        pg_enum(BannerLinkType, "banner_link_type"),
        nullable=False,
        server_default=BannerLinkType.NONE.value,
    )
    link_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[BannerPosition] = mapped_column(
        pg_enum(BannerPosition, "banner_position"), nullable=False
    )
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        Index("ix_banners_position_active", "position", "is_active", "sort"),
    )
