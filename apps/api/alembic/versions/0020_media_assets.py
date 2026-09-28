"""Add media_assets registry for v2 media resources.

ARCHITECTURE_PLAN.md §16 п.37: native clients cache images by a stable id, and
that id is ``uuid5`` of the S3 key. uuid5 is one-way, so the reverse lookup
(``id → key``, needed to issue the 307) requires a registry row.

Existing photos are backfilled in the same migration: a registry that only fills
on the next re-import would 404 on every catalog image until someone re-uploads
the whole library.

The backfill is computed in Python (``uuid.uuid5``), not in SQL, and that is not
a stylistic choice. The obvious SQL version needs ``uuid_generate_v5`` from
uuid-ossp, but the production PostgreSQL is a self-built binary whose
``share/postgresql/extension`` has no uuid-ossp.control, and the application
role is not a superuser — ``CREATE EXTENSION`` there fails with "extension is not
available". ``uuid.uuid5`` is stdlib, so the same derivation runs on every host.
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_media_assets"
down_revision: str | Sequence[str] | None = "0019_native_session_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same value as app.services.media.MEDIA_NAMESPACE. Duplicated on purpose:
# a migration must keep working after the application code moves on, and a
# change to the namespace would orphan every already-issued media id.
MEDIA_NAMESPACE = uuid.UUID("6f2c4a1e-7b3d-4c58-9a10-5d8e2f4b6c93")

THUMB_SUFFIX = "_thumb.webp"
THUMB_SIZE = 400
LARGE_SIZE = 1200
MIME_TYPE = "image/webp"

# Photos live only in these buckets (§10); anything else in the tables is a
# legacy/foreign key and must not get a media id.
PHOTO_KEY_PREFIXES = ("photos-series/", "photos-product/")


def _dimensions(s3_key: str) -> tuple[int, int]:
    return (THUMB_SIZE, THUMB_SIZE) if s3_key.endswith(THUMB_SUFFIX) else (LARGE_SIZE, LARGE_SIZE)


def _backfill_rows(keys: list[str]) -> list[dict[str, object]]:
    """Registry rows for the given S3 keys, deduplicated and prefix-filtered.

    Split out of ``upgrade`` so the id derivation — the part a migration cannot
    share with ``app.services.media`` without coupling the two — has a test:
    a wrong uuid5 here would hand every client an id that resolves to nothing.
    """
    now = datetime.now(timezone.utc)
    return [
        {
            "id": uuid.uuid5(MEDIA_NAMESPACE, key),
            "s3_key": key,
            "width": width,
            "height": height,
            "mime_type": MIME_TYPE,
            "created_at": now,
            "updated_at": now,
        }
        for key in sorted({k for k in keys if k and k.startswith(PHOTO_KEY_PREFIXES)})
        for width, height in (_dimensions(key),)
    ]


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("mime_type", sa.String(length=64), nullable=False, server_default="image/webp"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
        sa.UniqueConstraint("s3_key", name="uq_media_assets_s3_key"),
    )
    # No separate index on s3_key: the unique constraint already backs one.

    # Backfill from the two places photos live: series.photo_key and the product
    # gallery. Both may be NULL/empty, hence the filters.
    keys = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT photo_key AS key FROM series
                WHERE photo_key IS NOT NULL
                  AND photo_key <> ''
                UNION
                SELECT photo_key FROM product_photos
                WHERE photo_key <> ''
                """
            )
        )
        .scalars()
        .all()
    )
    rows = _backfill_rows(list(keys))
    if rows:
        op.bulk_insert(
            sa.table(
                "media_assets",
                sa.column("id", postgresql.UUID(as_uuid=True)),
                sa.column("s3_key", sa.String),
                sa.column("width", sa.Integer),
                sa.column("height", sa.Integer),
                sa.column("mime_type", sa.String),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_table("media_assets")
