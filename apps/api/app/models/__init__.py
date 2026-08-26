"""ORM-модели (SQLAlchemy 2.0).

Все модели импортируются здесь, чтобы:
  1. Alembic autogenerate видел все таблицы (через Base.metadata).
  2. `import app.models` регистрировал метаданные.

Схема — см. ARCHITECTURE_PLAN.md §5.
"""
from app.models.catalog import Brand, PriceHistory, PriceListVersion, Product, Series
from app.models.file import FileAsset
from app.models.order import Cart, CartItem, Order, OrderItem
from app.models.pricing import ExchangeRate, UserBrand
from app.models.system import AuditLog, Notification
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
    "Series",
    "Product",
    "PriceListVersion",
    "PriceHistory",
    # pricing
    "ExchangeRate",
    "UserBrand",
    # order
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    # file
    "FileAsset",
    # system
    "AuditLog",
    "Notification",
]
