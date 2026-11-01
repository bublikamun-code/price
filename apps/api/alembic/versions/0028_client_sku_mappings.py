"""Кросс-справочник клиентских артикулов: client_sku_mappings (§16 п.43).

ARCHITECTURE_PLAN.md §5.2 (client_sku_mappings), §6 «Кросс-справочник (v2)»,
docs/API_V2_CONTRACT.md §7.

Справочник «артикул клиента → наш SKU» на организацию (этап 7 роадмапа):
  * ``client_sku`` — CITEXT (расширение создаётся здесь же: 0001 создаёт его
    в одной транзакции с исходной схемой, но миграция должна быть
    идемпотентной и на свежих базах без 0001-порядка гарантий — checkfirst
    семантика IF NOT EXISTS): сравнение регистронезависимо, хранится как
    ввёл клиент, trim делает сервис;
  * ``product_id`` — FK **RESTRICT**: товар с архивацией не удаляется из БД,
    маппинг переживает архив (§16 п.43 п.8);
  * UNIQUE (organization_id, client_sku) — одна связка на артикул клиента;
  * INDEX (organization_id, created_at DESC) — список «свежие сверху».

Только CREATE TABLE/INDEX/EXTENSION — существующие таблицы не трогаются.

ORM-декларация — ``app/models/client_sku.py`` (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.types import CITEXT

revision: str = "0028_client_sku_mappings"
down_revision: str | Sequence[str] | None = "0027_order_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CITEXT нужен колонке client_sku; расширение создаёт и 0001, IF NOT
    # EXISTS делает повтор безопасным (паттерн миграции 0001).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "client_sku_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("client_sku", CITEXT(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Одна связка на артикул клиента в организации; CITEXT исключает
        # регистровые дубли («Вент-2» vs «вент-2»).
        sa.UniqueConstraint(
            "organization_id", "client_sku", name="uq_client_sku_mappings_org_sku"
        ),
        # Список справочника — свежие связки сверху.
        sa.Index(
            "ix_client_sku_mappings_org_created",
            "organization_id",
            sa.text("created_at DESC"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_client_sku_mappings_organization_id",
            ondelete="CASCADE",
        ),
        # RESTRICT: товар с архивацией не удаляется из БД — маппинг переживает
        # архив (§16 п.43 п.8).
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_client_sku_mappings_product_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_client_sku_mappings"),
    )


def downgrade() -> None:
    op.drop_table("client_sku_mappings")
    # Расширение citext не дропаем: его использует users.email (0001).
