"""Перечисления предметной области + хелпер для PostgreSQL ENUM-типов.

См. ARCHITECTURE_PLAN.md §5 (схема), §16 п.2 (упрощение stock_status).
"""
import enum

from sqlalchemy import Enum as SAEnum


class UserRole(str, enum.Enum):
    CLIENT = "CLIENT"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class OrganizationRole(str, enum.Enum):
    """Роль человека внутри коммерческой организации."""

    OWNER = "OWNER"
    BUYER = "BUYER"
    CONTACT = "CONTACT"
    VIEWER = "VIEWER"



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


class InvoiceStatus(str, enum.Enum):
    """Статус счёта на оплату (§16 п.40).

    Платёжного ledger нет — статусы переключает менеджер вручную; смена
    статуса счёта не трогает статус заказа и наоборот.
    """
    ISSUED = "ISSUED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class InvoicePdfStatus(str, enum.Enum):
    """Состояние рендера PDF счёта — вместо Redis-job (§10, §16 п.40).

    Счёт — постоянный документ, поэтому состояние живёт в колонке: после
    рестарта воркера он явно ``FAILED`` и перерендеривается, а не
    «теряется» вместе с TTL записи в Redis.
    """
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


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
    # Документы на товар/серию (§16 п.38): сертификаты и datasheets, PDF-only.
    CERTIFICATE = "CERTIFICATE"
    DATASHEET = "DATASHEET"
    # PDF счёта на оплату (§16 п.40): постоянный документ, visibility=AUTHED.
    INVOICE_PDF = "INVOICE_PDF"


class FileVisibility(str, enum.Enum):
    PUBLIC = "PUBLIC"             # доступен всем (даже гостям)
    AUTHED = "AUTHED"             # любому авторизованному
    MANAGER_ONLY = "MANAGER_ONLY"


class NewsType(str, enum.Enum):
    """Тип новости (§5)."""
    NEWS = "NEWS"
    NEW_PRODUCT = "NEW_PRODUCT"


class BannerLinkType(str, enum.Enum):
    """Тип ссылки баннера (главная страница)."""
    NONE = "NONE"
    PRODUCT = "PRODUCT"   # link_value — sku товара
    NEWS = "NEWS"         # link_value — id новости


class BannerPosition(str, enum.Enum):
    """Позиция баннера на главной."""
    PROMO = "PROMO"
    NEW = "NEW"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Создаёт SQLAlchemy ENUM-тип, хранящий значения enum (не имена).

    Используется в моделях. В миграции тип создаётся явно (create_type=False).
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )
