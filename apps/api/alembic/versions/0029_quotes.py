"""Коммерческие предложения: quotes + quote_items (этап 8 роадмапа).

docs/FEATURES_ROADMAP.md «Этап 8. Коммерческие предложения».

КП — документ менеджера с override-ценами и сроком действия:
  * ``quotes``: статус DRAFT/SENT/ACCEPTED/REJECTED/EXPIRED; ``seq``/``number``
    присваиваются при SEND (у DRAFT их нет — NULL); ``valid_until``
    обязателен к моменту SEND (валидация сервиса); ``version`` —
    optimistic concurrency (If-Match PATCH/send);
  * ``quote_items``: снапшот sku/name + ``unit_price`` из КП (без прайс-логики),
    при accept переезжает в order_items.unit_price; FK ``product_id`` RESTRICT
    (товар из КП не удаляется из БД, как у client_sku_mappings — §16 п.43 п.8),
    FK ``quote_id`` CASCADE;
  * ``quotes_seq_seq`` — PG-последовательность сквозных номеров (START 1:
    таблица пуста на момент миграции), nextval при SEND;
  * ``file_asset_type`` += ``QUOTE_PDF`` (PDF КП рендерится синхронно по
    запросу менеджера, FileAsset(type=QUOTE_PDF, visibility=AUTHED)).

ORM-декларация — ``app/models/quote.py`` (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_quotes"
down_revision: str | Sequence[str] | None = "0028_client_sku_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Тип файлового архива: PDF коммерческого предложения.
    #    ADD VALUE IF NOT EXISTS — идемпотентно (паттерн миграции 0023).
    op.execute("ALTER TYPE file_asset_type ADD VALUE IF NOT EXISTS 'QUOTE_PDF'")

    # 2) Статусы КП и состояния PDF-рендера. Значения enum создаются здесь
    #    явно (ORM объявляет их через pg_enum c create_type=False), а не на
    #    каждое использование — паттерн миграции 0023.
    quote_status = postgresql.ENUM(
        "DRAFT",
        "SENT",
        "ACCEPTED",
        "REJECTED",
        "EXPIRED",
        name="quote_status",
    )
    quote_status.create(op.get_bind(), checkfirst=True)
    quote_pdf_status = postgresql.ENUM(
        "PENDING", "READY", "FAILED", name="quote_pdf_status"
    )
    quote_pdf_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "DRAFT",
                "SENT",
                "ACCEPTED",
                "REJECTED",
                "EXPIRED",
                name="quote_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        # Номер/сквозной номер — только у отправленного КП (DRAFT: NULL).
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("number", sa.String(length=64), nullable=True),
        # DRAFT — пересчитывается при правках; SEND — заморозка (этап 8).
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column(
            "pdf_status",
            postgresql.ENUM(
                "PENDING", "READY", "FAILED", name="quote_pdf_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("pdf_file_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quotes"),
        # RESTRICT: организация с историей КП не удаляется каскадом.
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_quotes_organization_id",
            ondelete="RESTRICT",
        ),
        # Удаление менеджера не теряет документ (как у invoices.created_by).
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_quotes_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["pdf_file_asset_id"],
            ["file_assets.id"],
            name="fk_quotes_pdf_file_asset_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("seq", name="uq_quotes_seq"),
        sa.UniqueConstraint("number", name="uq_quotes_number"),
    )
    # Списки «свежие сверху» (клиент и менеджер) + фильтр по статусу.
    op.create_index(
        "ix_quotes_org_created",
        "quotes",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_quotes_status", "quotes", ["status"])

    op.create_table(
        "quote_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Снапшот на момент добавления позиции (переименование в каталоге не
        # переписывает составленное КП).
        sa.Column("sku", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quote_items"),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_quote_items_quote_id",
            ondelete="CASCADE",
        ),
        # RESTRICT: товар, вошедший в КП, не удаляется из БД (§16 п.43 п.8).
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_quote_items_product_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("qty >= 1", name="ck_quote_items_qty_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_quote_items_unit_price_positive"),
    )
    op.create_index(
        "ix_quote_items_quote_created",
        "quote_items",
        ["quote_id", "created_at"],
    )

    # 3) Сквозной номер КП из PG-sequence. Таблица пуста на момент миграции,
    #    поэтому START 1; nextval атомарен при конкурентном SEND (§16 п.9).
    op.execute("CREATE SEQUENCE quotes_seq_seq START WITH 1")


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE IF EXISTS quotes_seq_seq"))
    op.drop_index("ix_quote_items_quote_created", table_name="quote_items")
    op.drop_table("quote_items")
    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_org_created", table_name="quotes")
    op.drop_table("quotes")
    postgresql.ENUM(name="quote_pdf_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="quote_status").drop(op.get_bind(), checkfirst=True)
    # Значение QUOTE_PDF у PG-enum удалить нельзя — оставляем как есть (ADD
    # VALUE необратимо; поведение одинаково у соседних миграций 0023).
