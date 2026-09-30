"""Счёт на оплату: таблица invoices + реквизиты продавца/покупателя (§16 п.40).

ARCHITECTURE_PLAN.md §5.2 (invoices), §6 «Счета на оплату», §10, §16 п.40.

Счёт — замороженный документ 1:1 с заказом (``invoices.order_id UNIQUE``):
повторное выставление → 409 INVOICE_ALREADY_EXISTS, на заказе ``CANCELLED``
счёт не выставляется (409 ORDER_NOT_INVOICABLE).

Номер берётся из PG-последовательности ``invoices_seq_seq`` (nextval, а не
MAX+1 — тот же урок, что у ``orders_seq_seq``, §16 п.9); START = MAX(seq)+1
существующих данных. Последовательность независимая (без OWNED BY): «дыры»
при откате транзакции допустимы, а год входит только в печатный формат
``СЧ-YYYY-NNNNNN`` и не сбрасывает саму последовательность — сброс ломал бы
аудит и нумерацию уже выставленных счетов.
ORM-декларация — app/models/invoice.py (metadata → create_all в тестах).

Здесь же:
  * ``file_asset_type`` += ``INVOICE_PDF`` и nullable ``file_assets.order_id``
    (постоянный документ переживает удаление заказа, SET NULL);
  * enum-типы ``invoice_status`` / ``invoice_pdf_status`` — состояние рендера
    PDF живёт в колонке, а не в Redis-job (§10, §16 п.40 п.6);
  * банковские реквизиты покупателя ``organizations.bank_*`` (nullable).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_invoice"
down_revision: str | Sequence[str] | None = "0022_broadcast_reads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Тип файлового архива: PDF счёта на оплату.
    #    ADD VALUE не выполняется в транзакции в старых PG; начиная с PG 12 —
    #    внутри транзакции можно, IF NOT EXISTS делает миграцию идемпотентной.
    op.execute("ALTER TYPE file_asset_type ADD VALUE IF NOT EXISTS 'INVOICE_PDF'")

    # 2) Банковские реквизиты покупателя для счёта (§16 п.40 п.4).
    op.add_column(
        "organizations", sa.Column("bank_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("bank_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("bank_account", sa.String(length=64), nullable=True)
    )

    # 3) Привязка PDF счёта к заказу: счёт — постоянный документ, поэтому
    #    SET NULL (заказ удалён — архивный файл остаётся).
    op.add_column(
        "file_assets",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_file_assets_order_id",
        "file_assets",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_file_assets_order_id", "file_assets", ["order_id"])

    # 4) Статусы счёта. Значения enum создаются здесь явно (ORM объявляет их
    #    через pg_enum), а не на каждое использование — иначе создание колонки
    #    в тестовой схеме create_all разошлось бы с alembic check.
    invoice_status = postgresql.ENUM(
        "ISSUED", "PAID", "CANCELLED", name="invoice_status"
    )
    invoice_status.create(op.get_bind(), checkfirst=True)
    invoice_pdf_status = postgresql.ENUM(
        "PENDING", "READY", "FAILED", name="invoice_pdf_status"
    )
    invoice_pdf_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "ISSUED", "PAID", "CANCELLED", name="invoice_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "pdf_status",
            postgresql.ENUM(
                "PENDING",
                "READY",
                "FAILED",
                name="invoice_pdf_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("pdf_file_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Замороженная копия orders.total_amount на момент выставления (§16 п.40 п.3).
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        # 1:1 с заказом: второй счёт по заказу невозможен (переоформление —
        # вне этапа).
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_invoices_order_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pdf_file_asset_id"],
            ["file_assets.id"],
            name="fk_invoices_pdf_file_asset_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_invoices_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("order_id", name="uq_invoices_order_id"),
        sa.UniqueConstraint("seq", name="uq_invoices_seq"),
        sa.UniqueConstraint("number", name="uq_invoices_number"),
    )
    op.create_index("ix_invoices_status", "invoices", ["status"])

    # 5) Сквозной номер счёта из PG-sequence. Таблица пуста на момент
    #    миграции, но START считается по ней же — тот же паттерн, что в 0009
    #    для orders_seq_seq (устойчиво к повторному применению на данных).
    max_seq = (
        op.get_bind()
        .execute(sa.text("SELECT COALESCE(MAX(seq), 0) FROM invoices"))
        .scalar()
    )
    start = int(max_seq or 0) + 1
    op.execute(sa.text(f"CREATE SEQUENCE invoices_seq_seq START WITH {start}"))


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE IF EXISTS invoices_seq_seq"))
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_table("invoices")
    postgresql.ENUM(name="invoice_pdf_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="invoice_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_file_assets_order_id", table_name="file_assets")
    op.drop_constraint("fk_file_assets_order_id", "file_assets", type_="foreignkey")
    op.drop_column("file_assets", "order_id")

    op.drop_column("organizations", "bank_account")
    op.drop_column("organizations", "bank_code")
    op.drop_column("organizations", "bank_name")
    # Значение PG-enum удалить нельзя — оставляем как есть (ADD VALUE
    # необратимо до PG 12; поведение одинаково у соседних миграций).
