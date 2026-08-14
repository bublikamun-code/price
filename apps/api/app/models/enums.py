"""Перечисления предметной области + хелпер для PostgreSQL ENUM-типов.

См. ARCHITECTURE_PLAN.md §5 (схема), §16 п.2 (упрощение stock_status).
"""
import enum

from sqlalchemy import Enum as SAEnum


class UserRole(str, enum.Enum):
    CLIENT = "CLIENT"
    MANAGER = "MANAGER"


class StockStatus(str, enum.Enum):
    """Решение §16 п.2: упрощено до 2 значений + АРХИВ для soft-delete."""
    IN_STOCK = "IN_STOCK"     # «В наличии»
    PREORDER = "PREORDER"     # «Под заказ»
    ARCHIVED = "ARCHIVED"     # soft-delete при импорте (§7)


class OrderStatus(str, enum.Enum):
    """Жизненный цикл заявки (§9)."""
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ImportMode(str, enum.Enum):
    """Режимы импорта CSV (§7.2)."""
    UPSERT = "UPSERT"
    REPLACE = "REPLACE"
    ARCHIVE_MISSING = "ARCHIVE_MISSING"


class PriceListVersionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class FileAssetType(str, enum.Enum):
    BRAND_PDF = "BRAND_PDF"
    CUSTOM_CSV = "CUSTOM_CSV"
    PHOTO_ZIP = "PHOTO_ZIP"
    OTHER = "OTHER"


class FileVisibility(str, enum.Enum):
    PUBLIC = "PUBLIC"             # доступен всем (даже гостям)
    AUTHED = "AUTHED"             # любому авторизованному
    MANAGER_ONLY = "MANAGER_ONLY"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Создаёт SQLAlchemy ENUM-тип, хранящий значения enum (не имена).

    Используется в моделях. В миграции тип создаётся явно (create_type=False).
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )
