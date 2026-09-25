"""Добавить nullable structured delivery projection к заявкам.

Существующие v1 поля delivery_method/delivery_point сохраняются. Новые поля
позволяют v2-клиентам передавать адрес, контакт, телефон, предпочтительную дату
и комментарий без смешения этих данных с notes.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0011_structured_delivery"
down_revision: str | Sequence[str] | None = "0010_order_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("delivery_address", sa.String(500), nullable=True))
    op.add_column("orders", sa.Column("delivery_contact_name", sa.String(255), nullable=True))
    op.add_column("orders", sa.Column("delivery_phone", sa.String(50), nullable=True))
    op.add_column("orders", sa.Column("delivery_preferred_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("delivery_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "delivery_comment")
    op.drop_column("orders", "delivery_preferred_date")
    op.drop_column("orders", "delivery_phone")
    op.drop_column("orders", "delivery_contact_name")
    op.drop_column("orders", "delivery_address")
