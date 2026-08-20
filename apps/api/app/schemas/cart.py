"""DTO корзины клиента (Этап 6). См. ARCHITECTURE_PLAN.md §6."""
import uuid

from pydantic import BaseModel, Field, model_validator


class CartItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, default=1)
    note: str | None = None


class CartItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    note: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.quantity is None and self.note is None:
            raise ValueError("Укажите quantity и/или note")
        return self


class CartItemRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    brand_name: str | None
    photo_key: str | None
    stock_status: str
    quantity: int
    note: str | None
    unit_price: float
    currency: str
    line_total: float


class CartRead(BaseModel):
    id: uuid.UUID
    items: list[CartItemRead]
    total_amount: float
    total_items: int


# ----------------------------- bulk-добавление (§16 п.20-5) -----------------------------

BULK_ITEMS_MAX = 500


class CartBulkItemIn(BaseModel):
    """Строка bulk-запроса: артикул + количество (≥ 1)."""
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1)


class CartBulkAddIn(BaseModel):
    items: list[CartBulkItemIn] = Field(min_length=1, max_length=BULK_ITEMS_MAX)


class CartBulkAdded(BaseModel):
    """Добавленная позиция: quantity — итоговое количество в корзине."""
    sku: str
    quantity: int


class CartBulkRejected(BaseModel):
    sku: str
    reason: str


class CartBulkAddOut(BaseModel):
    """Итог bulk-добавления: частичный успех (код всегда 200)."""
    added: list[CartBulkAdded]
    rejected: list[CartBulkRejected]
