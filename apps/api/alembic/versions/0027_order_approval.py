"""Согласование заявок в организации: настройки на organizations + виза на orders (§16 п.42).

ARCHITECTURE_PLAN.md §5.2 (organizations, orders), §6 «Согласование заявок (v2)»,
§9, docs/API_V2_CONTRACT.md §7/§12.

Решения (§16 п.42):
  * ``organizations.approval_mode`` (enum OFF/ALL/OVER_LIMIT, default OFF) +
    ``approval_limit_amount NUMERIC(14,2) NULL`` — режим и порог «сверх лимита»
    (граница строгая: виза нужна при ``total_amount > limit``);
  * ``orders.approval_status`` (enum NOT_REQUIRED/PENDING/APPROVED/REJECTED,
    default NOT_REQUIRED) — отдельный гейт ВНЕ FSM OrderStatus (§9 не тронут);
  * ``approved_by``/``approved_at`` — кто и когда выдал визу;
    ``rejection_reason`` — обязательная причина отказа при REJECTED;
  * частичный индекс ``ix_orders_pending_approval`` (только PENDING) под
    менеджерский список «ждут согласования» — таких строк единицы.

Совместимость с существующими данными: обе колонки получают server_default
(OFF / NOT_REQUIRED), поэтому backfill не нужен; виза появляется только у
новых заявок. Только ADD COLUMN + CREATE TYPE/INDEX — ни DROP, ни ALTER
существующих колонок.

ORM-декларация — app/models/organization.py, app/models/order.py
(metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_order_approval"
down_revision: str | Sequence[str] | None = "0026_email_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) PG-enum-типы. Значения создаются здесь явно (ORM объявляет их через
    #    pg_enum), а не на каждое использование — паттерн миграции 0023:
    #    иначе создание колонки в тестовой схеме create_all разошлось бы с
    #    alembic check. checkfirst делает миграцию идемпотентной.
    approval_mode = postgresql.ENUM("OFF", "ALL", "OVER_LIMIT", name="approval_mode")
    approval_mode.create(op.get_bind(), checkfirst=True)
    approval_status = postgresql.ENUM(
        "NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", name="approval_status"
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    # 2) Настройки режима на организации (§16 п.42 п.1).
    op.add_column(
        "organizations",
        sa.Column(
            "approval_mode",
            postgresql.ENUM(
                "OFF", "ALL", "OVER_LIMIT", name="approval_mode", create_type=False
            ),
            server_default="OFF",
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("approval_limit_amount", sa.Numeric(precision=14, scale=2), nullable=True),
    )

    # 3) Гейт согласования на заявке (§16 п.42 п.4): default NOT_REQUIRED —
    #    существующие заявки считаются согласованными (виза не требуется).
    op.add_column(
        "orders",
        sa.Column(
            "approval_status",
            postgresql.ENUM(
                "NOT_REQUIRED",
                "PENDING",
                "APPROVED",
                "REJECTED",
                name="approval_status",
                create_type=False,
            ),
            server_default="NOT_REQUIRED",
            nullable=False,
        ),
    )
    # Виза: SET NULL — пользователь удалён, факт визы и причина остаются.
    op.add_column(
        "orders",
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_orders_approved_by",
        "orders",
        "users",
        ["approved_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "orders",
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )

    # 4) Частичный индекс под список «ждут согласования» (§16 п.42 п.9).
    op.create_index(
        "ix_orders_pending_approval",
        "orders",
        ["approval_status"],
        postgresql_where=sa.text("approval_status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_pending_approval", table_name="orders")
    op.drop_constraint("fk_orders_approved_by", "orders", type_="foreignkey")
    op.drop_column("orders", "rejection_reason")
    op.drop_column("orders", "approved_at")
    op.drop_column("orders", "approved_by")
    op.drop_column("orders", "approval_status")
    op.drop_column("organizations", "approval_limit_amount")
    op.drop_column("organizations", "approval_mode")
    postgresql.ENUM(name="approval_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="approval_mode").drop(op.get_bind(), checkfirst=True)
