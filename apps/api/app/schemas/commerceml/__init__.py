"""Слой DTO CommerceML 2.x для обмена с 1С (§18.3).

JSON-адаптация CommerceML: общие элементы, документы заказов, прайса и
остатков. Отдельный пакет (а не ``schemas/order.py``) — контракт 1С версионируется
независимо от внутренних DTO портала и не должен тащить за собой изменения
при правках заявок.
"""
from app.schemas.commerceml.common import (
    SCHEMA_VERSION,
    CommerceMLModel,
    ExchangeStamp,
    PriceValue,
    ProductIdentifier,
    Warehouse,
)
from app.schemas.commerceml.orders import (
    OrderCustomer,
    OrderDocument,
    OrderLine,
    OrderStatusChange,
)
from app.schemas.commerceml.prices import PriceDocument, PriceItem
from app.schemas.commerceml.stock import StockDocument, StockItem

__all__ = [
    "SCHEMA_VERSION",
    "CommerceMLModel",
    "ExchangeStamp",
    "OrderCustomer",
    "OrderDocument",
    "OrderLine",
    "OrderStatusChange",
    "PriceDocument",
    "PriceItem",
    "PriceValue",
    "ProductIdentifier",
    "StockDocument",
    "StockItem",
    "Warehouse",
]