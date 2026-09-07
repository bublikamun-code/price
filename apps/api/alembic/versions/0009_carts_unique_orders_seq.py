"""carts UNIQUE(user_id) + PG-последовательность для orders.seq

Аудит 2026-09-06:
  - carts.user_id → UNIQUE (``uq_carts_user_id``): гонка get_or_create
    (check-then-insert) создавала две корзины одному клиенту. Перед
    добавлением ограничения — дедупликация: на пользователя остаётся самая
    свежая корзина (по ``created_at, id``); содержимое дубликатов удаляется
    вместе с корзинами (cart_items — FK ON DELETE CASCADE).
  - последовательность ``orders_seq_seq`` для сквозных номеров заявок:
    nextval вместо MAX(seq)+1 — конкурентное создание заявок больше не
    падает по ``uq_orders_seq`` с 500. START = MAX(seq)+1 существующих
    данных; последовательность независимая (без OWNED BY): «дыры» при
    откате транзакции допустимы, номер сквозной, не бухгалтерский.
    ORM-декларация — app/models/order.py (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0009_carts_unique_orders_seq"
down_revision: str | Sequence[str] | None = "0008_pwd_change_grace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Дедупликация корзин: на каждого пользователя оставляем одну корзину —
    #    самую свежую (максимум по паре (created_at, id)). Строки cart_items
    #    дубликатов удаляются автоматически (FK ON DELETE CASCADE).
    op.execute(
        sa.text(
            """
            DELETE FROM carts c
            USING carts keeper
            WHERE c.user_id = keeper.user_id
              AND c.id <> keeper.id
              AND (keeper.created_at > c.created_at
                   OR (keeper.created_at = c.created_at AND keeper.id > c.id))
            """
        )
    )
    # 2) Одна корзина на клиента: параллельный check-then-insert теперь
    #    детерминированно проигрывает по IntegrityError (обрабатывается в
    #    repositories/cart.get_or_create_cart через SAVEPOINT).
    op.create_unique_constraint("uq_carts_user_id", "carts", ["user_id"])
    # 3) Сквозные номера заявок из PG-sequence, START за существующими данными
    #    (int() — страховка от нечисловых значений в DDL).
    max_seq = (
        op.get_bind()
        .execute(sa.text("SELECT COALESCE(MAX(seq), 0) FROM orders"))
        .scalar()
    )
    start = int(max_seq or 0) + 1
    op.execute(sa.text(f"CREATE SEQUENCE orders_seq_seq START WITH {start}"))


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE IF EXISTS orders_seq_seq"))
    op.drop_constraint("uq_carts_user_id", "carts", type_="unique")
