"""ORM-модели (SQLAlchemy 2.0).

Все модели импортируются здесь, чтобы:
  1. Alembic autogenerate видел все таблицы (через Base.metadata).
  2. `import app.models` регистрировал метаданные.

Схема — см. ARCHITECTURE_PLAN.md §5.
"""
from app.models.banner import Banner
from app.models.catalog import (
    Brand,
    BrandVolumeTier,
    PriceHistory,
    PriceListVersion,
    Product,
    ProductPhoto,
    Series,
)
from app.models.file import FileAsset, MediaAsset
from app.models.invoice import Invoice
from app.models.news import News
from app.models.order import Cart, CartItem, Order, OrderIdempotency, OrderItem
from app.models.organization import (
    Organization,
    OrganizationAddress,
    OrganizationBrandTerm,
    OrganizationMembership,
    OrganizationPricingAgreement,
)
from app.models.pricing import ExchangeRate, UserBrand
from app.models.system import AuditLog, Notification, NotificationReadState
from app.models.user import (
    ConsentLog,
    Favorite,
    PasswordResetToken,
    Session,
    TotpRecoveryCode,
    User,
)

__all__ = [
    # user
    "User",
    "Session",
    "TotpRecoveryCode",
    "ConsentLog",
    "PasswordResetToken",
    "Favorite",
    # catalog
    "Brand",
    "BrandVolumeTier",
    "Series",
    "Product",
    "ProductPhoto",
    "PriceListVersion",
    "PriceHistory",
    # pricing
    "ExchangeRate",
    "UserBrand",
    # organization
    "Organization",
    "OrganizationMembership",
    "OrganizationPricingAgreement",
    "OrganizationBrandTerm",
    "OrganizationAddress",
    # order
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "OrderIdempotency",
    # invoice (§16 п.40)
    "Invoice",
    # file
    "FileAsset",
    "MediaAsset",
    # system
    "AuditLog",
    "Notification",
    "NotificationReadState",
    # news
    "News",
    # banner
    "Banner",
]
