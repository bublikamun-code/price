"""Reconcile model constraints on databases initialized before FK drift was tracked.

The local/staging schema predates the model-level foreign keys on operational
records.  These additions are guarded so a clean migration chain remains a
no-op when the constraints already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_reconcile_model_constraints"
down_revision: Union[str, Sequence[str], None] = "0016_cart_org_scope_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FOREIGN_KEYS = (
    ("audit_log", "actor_id", "users", "SET NULL", "fk_audit_log_actor_id_users"),
    ("consent_log", "user_id", "users", "CASCADE", "fk_consent_log_user_id_users"),
    ("favorites", "user_id", "users", "CASCADE", "fk_favorites_user_id_users"),
    ("notifications", "user_id", "users", "CASCADE", "fk_notifications_user_id_users"),
    ("password_reset_tokens", "user_id", "users", "CASCADE", "fk_password_reset_tokens_user_id_users"),
    ("price_list_versions", "uploaded_by", "users", None, "fk_price_list_versions_uploaded_by_users"),
    ("price_list_versions", "rolled_back_by", "users", None, "fk_price_list_versions_rolled_back_by_users"),
    ("sessions", "user_id", "users", "CASCADE", "fk_sessions_user_id_users"),
    ("totp_recovery_codes", "user_id", "users", "CASCADE", "fk_totp_recovery_codes_user_id_users"),
    ("user_brands", "user_id", "users", "CASCADE", "fk_user_brands_user_id_users"),
    ("user_brands", "updated_by", "users", None, "fk_user_brands_updated_by_users"),
)


def _foreign_key_exists(inspector: sa.Inspector, table: str, column: str, referred_table: str) -> bool:
    return any(
        foreign_key.get("constrained_columns") == [column]
        and foreign_key.get("referred_table") == referred_table
        for foreign_key in inspector.get_foreign_keys(table)
    )


def _favorites_constraint_named(inspector: sa.Inspector, name: str) -> bool:
    primary_key = inspector.get_pk_constraint("favorites")
    if primary_key.get("name") == name:
        return True
    return any(unique.get("name") == name for unique in inspector.get_unique_constraints("favorites"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column, referred_table, ondelete, name in _FOREIGN_KEYS:
        if not _foreign_key_exists(inspector, table, column, referred_table):
            op.create_foreign_key(name, table, referred_table, [column], ["id"], ondelete=ondelete)

    if not _favorites_constraint_named(inspector, "uq_favorites_user_product"):
        primary_key = inspector.get_pk_constraint("favorites")
        if primary_key.get("name") == "uq_favorites_user_product":
            op.execute(
                "ALTER TABLE favorites RENAME CONSTRAINT "
                "uq_favorites_user_product TO pk_favorites_user_product"
            )
            inspector = sa.inspect(bind)
        op.create_unique_constraint("uq_favorites_user_product", "favorites", ["user_id", "product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column, referred_table, ondelete, name in reversed(_FOREIGN_KEYS):
        if _foreign_key_exists(inspector, table, column, referred_table):
            op.drop_constraint(name, table, type_="foreignkey")

    if any(
        unique.get("name") == "uq_favorites_user_product"
        for unique in inspector.get_unique_constraints("favorites")
    ):
        op.drop_constraint("uq_favorites_user_product", "favorites", type_="unique")
        inspector = sa.inspect(bind)
        if inspector.get_pk_constraint("favorites").get("name") == "pk_favorites_user_product":
            op.execute(
                "ALTER TABLE favorites RENAME CONSTRAINT "
                "pk_favorites_user_product TO uq_favorites_user_product"
            )
