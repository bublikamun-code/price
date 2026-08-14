"""user price digest opt-in

Revision ID: 863ddb771b92
Revises: 0002_product_attributes
Create Date: 2026-08-14 06:47:44.337542

Opt-in клиента на дайджест изменения цен (§20.4):
  - price_digest_enabled  — включено/выключено (default false)
  - price_digest_sources  — источники отслеживания: cart/favorite/orders
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '863ddb771b92'
down_revision: Union[str, Sequence[str], None] = '0002_product_attributes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'price_digest_enabled',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'price_digest_sources',
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("ARRAY['cart','favorite','orders']::varchar[]"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'price_digest_sources')
    op.drop_column('users', 'price_digest_enabled')
