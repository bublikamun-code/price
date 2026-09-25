"""Finish reconciliation for pre-existing local schema constraint names."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_fix_constraint_drift"
down_revision: Union[str, Sequence[str], None] = "0017_reconcile_model_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _foreign_key_exists(inspector: sa.Inspector, table: str, column: str, referred_table: str) -> bool:
    return any(
        foreign_key.get("constrained_columns") == [column]
        and foreign_key.get("referred_table") == referred_table
        for foreign_key in inspector.get_foreign_keys(table)
    )


def _favorites_unique_exists(inspector: sa.Inspector) -> bool:
    return any(
        unique.get("name") == "uq_favorites_user_product"
        for unique in inspector.get_unique_constraints("favorites")
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _foreign_key_exists(inspector, "user_brands", "user_id", "users"):
        op.create_foreign_key(
            "fk_user_brands_user_id_users",
            "user_brands",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _favorites_unique_exists(inspector):
        primary_key = inspector.get_pk_constraint("favorites")
        if primary_key.get("name") == "uq_favorites_user_product":
            op.execute(
                "ALTER TABLE favorites RENAME CONSTRAINT "
                "uq_favorites_user_product TO pk_favorites_user_product"
            )
        op.create_unique_constraint("uq_favorites_user_product", "favorites", ["user_id", "product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _favorites_unique_exists(inspector):
        op.drop_constraint("uq_favorites_user_product", "favorites", type_="unique")
        inspector = sa.inspect(bind)
        if inspector.get_pk_constraint("favorites").get("name") == "pk_favorites_user_product":
            op.execute(
                "ALTER TABLE favorites RENAME CONSTRAINT "
                "pk_favorites_user_product TO uq_favorites_user_product"
            )

    if _foreign_key_exists(inspector, "user_brands", "user_id", "users"):
        op.drop_constraint("fk_user_brands_user_id_users", "user_brands", type_="foreignkey")
