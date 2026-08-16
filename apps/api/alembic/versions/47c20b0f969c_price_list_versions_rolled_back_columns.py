"""price_list_versions rolled_back columns

Revision ID: 47c20b0f969c
Revises: 0003_products_sku_trgm
Create Date: 2026-08-16 13:42:04.110246

Аудит отката версии прайса (§16 п.14):
  - rolled_back_at — когда версия откачена (NULL — откат не выполнялся);
  - rolled_back_by — кто откатил (FK → users.id, как uploaded_by).

Autogenerate выдал также шум server_default по всем таблицам (DB vs модели)
и drop посторонних индексов — вычищено: в миграции только эти 2 колонки и FK.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '47c20b0f969c'
down_revision: Union[str, Sequence[str], None] = '0003_products_sku_trgm'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = 'price_list_versions_rolled_back_by_fkey'


def upgrade() -> None:
    op.add_column(
        'price_list_versions',
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'price_list_versions',
        sa.Column('rolled_back_by', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        _FK_NAME, 'price_list_versions', 'users', ['rolled_back_by'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, 'price_list_versions', type_='foreignkey')
    op.drop_column('price_list_versions', 'rolled_back_by')
    op.drop_column('price_list_versions', 'rolled_back_at')
