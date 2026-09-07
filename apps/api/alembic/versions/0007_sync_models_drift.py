"""sync models drift: missing tables/columns (hand-pruned autogenerate)

Revision ID: 0007_sync_drift
Revises: 0006_user_telegram
Create Date: 2026-09-05

Консолидация дрейфа «модели vs миграции», накопившегося после 7412363
(2FA, forgot-password, доставка): отсутствующие таблицы и колонки, которые
не попали в миграции. Только аддитивные операции — alter_column
server_default и дропы индексов из autogenerate вычищены (они ломали бы
дефолты БД). При необходимости индексы выравниваются отдельно.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0007_sync_drift"
down_revision: Union[str, Sequence[str], None] = "0006_user_telegram"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Таблицы 2FA/forgot-password (7412363), потерянные из миграций ---
    op.create_table(
        "password_reset_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"),
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "totp_recovery_codes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )

    # --- products.stock_qty (модель читается сидом каталога и каталогом) ---
    op.add_column("products", sa.Column("stock_qty", sa.Integer(), nullable=True))

    # --- Заявки: способ доставки и сквозной номер (модели orders) ---
    op.add_column(
        "orders",
        sa.Column(
            "delivery_method", sa.String(length=20), server_default="pickup",
            nullable=False,
        ),
    )
    op.add_column("orders", sa.Column("delivery_point", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("seq", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_orders_seq", "orders", ["seq"])

    # --- Уникальность пары (user, product) в избранном (по моделям) ---
    op.create_unique_constraint(
        "uq_favorites_user_product", "favorites", ["user_id", "product_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_favorites_user_product", "favorites", type_="unique")
    op.drop_constraint("uq_orders_seq", "orders", type_="unique")
    op.drop_column("orders", "seq")
    op.drop_column("orders", "delivery_point")
    op.drop_column("orders", "delivery_method")
    op.drop_column("products", "stock_qty")
    op.drop_table("totp_recovery_codes")
    op.drop_index(
        op.f("ix_password_reset_tokens_user_id"), table_name="password_reset_tokens"
    )
    op.drop_table("password_reset_tokens")
