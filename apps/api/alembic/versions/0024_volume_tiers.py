"""Скидки за объём: brand_volume_tiers + brands.version (§16 п.41).

ARCHITECTURE_PLAN.md §5.2 (brand_volume_tiers), §6 «Скидки за объём», §7.4, §8,
§16 п.41.

Лестница «от N шт — X%» задаётся на **бренд**. Порог сравнивается с количеством
одной строки корзины/заказа; действует одна ступень — наибольшая с
``min_qty <= quantity``; ступени не суммируются. С процентом по бренду
(``organization_brand_terms`` либо legacy ``user_brands``) берётся максимум из
двух процентов, а не сумма. ``products.override_price`` не подвержен объёмной
скидке — жёсткая цена из CSV остаётся приоритетом §8 п.1.

``brands.version`` добавлена здесь же: в таблице бренда колонки версии не было,
а ``If-Match`` по §6 на правку лестницы опереться было не на что. Изначально 1,
обновляется только через PATCH бренда/ступени — фолбэка на ``updated_at`` нет,
потому что он меняется и от импорта CSV, и от загрузки фото серии.

ORM-декларация — ``app/models/catalog.py`` (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_volume_tiers"
down_revision: str | Sequence[str] | None = "0023_invoice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Версия бренда — база для If-Match (§16 п.41 п.8).
    op.add_column(
        "brands",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # 2) Лестница скидок за объём.
    op.create_table(
        "brand_volume_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_qty", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
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
        # Два порога с одинаковым min_qty в пределах бренда невозможны —
        # иначе «лучшая подходящая ступень» была бы неоднозначной.
        sa.UniqueConstraint(
            "brand_id", "min_qty", name="uq_brand_volume_tiers_brand_min_qty"
        ),
        # Выбор ступени — последняя строка выборки по (brand_id, min_qty DESC).
        sa.Index(
            "ix_brand_volume_tiers_brand_min_qty",
            "brand_id",
            sa.text("min_qty DESC"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name="fk_brand_volume_tiers_brand_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_volume_tiers"),
    )

    # 3) Домены значений: min_qty >= 1, 0 < discount_percent < 100.
    #    Ноль процентов бессмысленен (ступень без эффекта), а 100 — это отдача
    #    товара без оплаты; оба значения нельзя хранить как «скидку».
    op.create_check_constraint(
        "ck_brand_volume_tiers_min_qty_positive",
        "brand_volume_tiers",
        "min_qty >= 1",
    )
    op.create_check_constraint(
        "ck_brand_volume_tiers_discount_range",
        "brand_volume_tiers",
        "discount_percent > 0 AND discount_percent < 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_brand_volume_tiers_discount_range", "brand_volume_tiers", type_="check"
    )
    op.drop_constraint(
        "ck_brand_volume_tiers_min_qty_positive", "brand_volume_tiers", type_="check"
    )
    op.drop_index("ix_brand_volume_tiers_brand_min_qty", table_name="brand_volume_tiers")
    op.drop_table("brand_volume_tiers")
    op.drop_column("brands", "version")
