"""Индексы под рантайм-выборки repositories/ (§5.2, §5.2 «Индексы»).

ARCHITECTURE_PLAN.md §5.2 — список индексов `products` дополнен перечнем
рантайм-индексов; этот список и есть основание для миграции.

Задача: в `apps/api/app/repositories/*.py` выборки идут по колонкам, для которых
в моделях нет индекса. Ниже — только `CREATE INDEX` (ни одной `DROP`, ни одной
`ALTER`), поэтому миграция безопасна для существующих данных и полностью
обратима: ``downgrade`` роняет ровно те индексы, которые создал ``upgrade``.

Принцип (см. §5.2):
  * составной btree покрывает связку «фильтр + сортировка» того же запроса;
  * частичный индекс — под soft-delete (``deleted_at IS NULL``), чтобы архивные
    товары не раздували индекс каталога;
  * DESC ставится там, где сортировка в репозитории идёт по убыванию —
    обычный ASC-индекс всё равно читается backward, а вот смешанные запросы
    (фильтр по одной колонке + DESC по другой) требуют именно такого порядка.

Чего миграция НЕ делает и почему:
  * ``users.email`` уже UNIQUE (``uq_users_email``, CITEXT) — дублировать нельзя;
  * ``brands.slug``, ``media_assets.s3_key``, ``sessions.refresh_token_hash``,
    ``totp_recovery_codes.code_hash``, ``password_reset_tokens.token_hash``,
    ``invoices (order_id|seq|number)``, ``cart_items (cart_id, product_id)``,
    ``user_brands (user_id, brand_id)``, ``favorites (user_id, product_id)`` —
    уникальные/PK уже покрывают эти выборки;
  * ``consent_log.user_id`` — в коде только INSERT (``services/auth.py``),
    выборок по нему нет, индекс был бы «про запас», а не по факту;
  * ``order_idempotency_keys.order_id``, ``cart_items.product_id``,
    ``notification_reads.notification_id`` — выборки идут по ведущим колонкам
    существующих составных уникальных индексов, дублировать не нужно;
  * ``invoices.status``/``created_by``, ``organizations.is_active`` — индексы
    уже есть (миграции 0023 / 0013).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_add_missing_indexes"
down_revision: str | Sequence[str] | None = "0024_volume_tiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # order_items: таблица была без единого индекса, кроме PK по id.
    # positions читаются и фильтруются по ней на каждой карточке заявки.
    # ------------------------------------------------------------------
    # repositories/orders.py:246 — get_order_items:
    #   WHERE order_id = :id ORDER BY created_at
    # repositories/orders.py:134 — _v2_search_filter: коррелированный EXISTS
    #   по order_items от заявки (join размножил бы строки и сломал бы keyset).
    op.create_index(
        "ix_order_items_order_created", "order_items", ["order_id", "created_at"]
    )
    # repositories/dashboard.py:91, repositories/manager_catalog.py:114 —
    # «Топ товаров» клиента и менеджера: GROUP BY order_items.product_id.
    # Без индекса агрегат читает всю таблицу позиций.
    op.create_index("ix_order_items_product", "order_items", ["product_id"])

    # ------------------------------------------------------------------
    # series: FK на brands без индекса — фильтр серий по бренду.
    # ------------------------------------------------------------------
    # repositories/public.py:26 (серии бренда), :95 (счётчик серий бренда),
    # :113 (серии с фото); repositories/catalog.py:457 (upsert по имени+бренду);
    # repositories/manager_catalog.py:273 (GROUP BY brand_id), :309 (счётчик).
    op.create_index("ix_series_brand", "series", ["brand_id"])

    # ------------------------------------------------------------------
    # price_list_versions: таблица была без индексов, кроме PK.
    # ------------------------------------------------------------------
    # repositories/catalog.py:583 — список версий импорта «новые сверху»
    # без фильтров: ORDER BY created_at DESC LIMIT/OFFSET.
    op.create_index(
        "ix_price_list_versions_created",
        "price_list_versions",
        [sa.text("created_at DESC")],
    )
    # repositories/price_changes.py:32 — предыдущая завершённая (DONE) версия:
    #   WHERE status = 'DONE' AND id <> :id ORDER BY created_at DESC LIMIT 1
    # repositories/manager_catalog.py:82 — счётчик версий по статусам.
    op.create_index(
        "ix_price_list_versions_status_created",
        "price_list_versions",
        ["status", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # price_history.price_list_version_id: снимок цен версии для дайджеста.
    # Существующий ix_price_history_product_time ведёт по product_id, а
    # repositories/price_changes.py:55,:68 фильтрует по версии.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_price_history_version", "price_history", ["price_list_version_id"]
    )

    # ------------------------------------------------------------------
    # orders.manager_id: список заявок менеджера. ix_orders_client_created и
    # ix_orders_organization_created ведут по client_id/organization_id,
    # manager_id оставался без индекса (organizations.py, orders.py).
    # ------------------------------------------------------------------
    # repositories/orders.py:63,:70 и :91 — WHERE manager_id = :id
    #   ORDER BY created_at DESC LIMIT/OFFSET.
    op.create_index(
        "ix_orders_manager_created",
        "orders",
        ["manager_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # users.role: обе админские выборки фильтруют по роли и сортируют по дате.
    # ------------------------------------------------------------------
    # repositories/users.py:49,:56 — клиенты: WHERE role='CLIENT'
    #   ORDER BY created_at DESC (+ счётчик :59,:88).
    # repositories/admin.py:16 — менеджеры: WHERE role='MANAGER'
    #   ORDER BY created_at DESC.
    op.create_index(
        "ix_users_role_created", "users", ["role", sa.text("created_at DESC")]
    )

    # ------------------------------------------------------------------
    # notifications: лента «новые сверху» + фильтр по типу.
    # Существующий ix_notif_user_unread частичный (user_id WHERE is_read=false)
    # не помогает ни сортировке ленты, ни выборке по типу уведомления.
    # ------------------------------------------------------------------
    # repositories/notifications.py:105 — ORDER BY created_at DESC, id DESC.
    op.create_index(
        "ix_notifications_created", "notifications", [sa.text("created_at DESC")]
    )
    # repositories/notifications.py:84,:105 — лента с фильтром ?type=…
    op.create_index(
        "ix_notifications_type_created",
        "notifications",
        ["type", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # products: сортировки дашборда и каталога.
    # ------------------------------------------------------------------
    # repositories/dashboard.py:172 — «Новинки»: WHERE deleted_at IS NULL
    #   ORDER BY created_at DESC, id DESC LIMIT 5.
    op.create_index(
        "ix_products_created", "products", [sa.text("created_at DESC")]
    )
    # repositories/dashboard.py:190,:193 — «Акции»: WHERE deleted_at IS NULL
    #   AND override_price IS NOT NULL ORDER BY updated_at DESC, id DESC.
    op.create_index(
        "ix_products_updated", "products", [sa.text("updated_at DESC")]
    )
    # repositories/catalog.py:113 (сортировка по умолчанию),
    # :138,:143 (keyset-страница v2), :197 (выгрузка каталога) —
    #   WHERE deleted_at IS NULL AND stock_status <> 'ARCHIVED'
    #   ORDER BY name ASC|DESC, id ASC|DESC.
    # Частичный предикат повторяет WHERE списка: архивные строки в индекс не
    # попадают, а GIN/trgm-индексы продолжают обслуживать ILIKE-поиск.
    op.create_index(
        "ix_products_active_name",
        "products",
        ["name"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # repositories/catalog.py:110,:140 — те же выборки, сортировка по цене.
    op.create_index(
        "ix_products_active_price",
        "products",
        ["base_price"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # file_assets: архив файлов фильтруется по типу/бренду/видимости и
    # сортируется по дате. Индексы на FK (product_id/series_id/order_id)
    # созданы миграциями 0020/0021/0023; brand_id, type и порядок — нет.
    # ------------------------------------------------------------------
    # repositories/file_assets.py:66,:69 — архив: фильтры + created_at DESC.
    op.create_index(
        "ix_file_assets_created", "file_assets", [sa.text("created_at DESC")]
    )
    # repositories/file_assets.py:43,:45 — архив с фильтром по бренду и типу.
    op.create_index("ix_file_assets_brand_type", "file_assets", ["brand_id", "type"])
    # repositories/file_assets.py:43 — архив только по типу (без бренда).
    op.create_index("ix_file_assets_type", "file_assets", ["type"])

    # ------------------------------------------------------------------
    # product_photos: первое фото товара выбирается коррелированным
    # подзапросом LIMIT 1 на КАЖДУЮ строку каталога/витрины — то есть
    # N+1 на уровне SQL. Индекс (product_id, sort_order, created_at)
    # превращает его в index-only scan, возвращающий ровно одну строку.
    # ------------------------------------------------------------------
    # repositories/catalog.py:66-69 (витрина клиента), :324-326 (карточка),
    # repositories/public.py:64-66 (SEO-витрина), :103-106 (список SKU).
    op.create_index(
        "ix_product_photos_product_sort",
        "product_photos",
        ["product_id", "sort_order", "created_at"],
    )

    # ------------------------------------------------------------------
    # totp_recovery_codes.user_id: FK без индекса; выборка кодов менеджера
    # при входе/включении 2FA.
    # ------------------------------------------------------------------
    # services/auth.py:415, :475, :524-526 — SELECT ... WHERE user_id = :id
    # (в т.ч. «неиспользованные коды» user_id + used_at IS NULL).
    op.create_index("ix_totp_recovery_codes_user", "totp_recovery_codes", ["user_id"])


def downgrade() -> None:
    """Роняет ровно те индексы, которые создал upgrade — в обратном порядке."""
    op.drop_index("ix_totp_recovery_codes_user", table_name="totp_recovery_codes")
    op.drop_index(
        "ix_product_photos_product_sort", table_name="product_photos"
    )
    op.drop_index("ix_file_assets_type", table_name="file_assets")
    op.drop_index("ix_file_assets_brand_type", table_name="file_assets")
    op.drop_index("ix_file_assets_created", table_name="file_assets")
    op.drop_index("ix_products_active_price", table_name="products")
    op.drop_index("ix_products_active_name", table_name="products")
    op.drop_index("ix_products_updated", table_name="products")
    op.drop_index("ix_products_created", table_name="products")
    op.drop_index("ix_notifications_type_created", table_name="notifications")
    op.drop_index("ix_notifications_created", table_name="notifications")
    op.drop_index("ix_users_role_created", table_name="users")
    op.drop_index("ix_orders_manager_created", table_name="orders")
    op.drop_index("ix_price_history_version", table_name="price_history")
    op.drop_index(
        "ix_price_list_versions_status_created", table_name="price_list_versions"
    )
    op.drop_index(
        "ix_price_list_versions_created", table_name="price_list_versions"
    )
    op.drop_index("ix_series_brand", table_name="series")
    op.drop_index("ix_order_items_product", table_name="order_items")
    op.drop_index("ix_order_items_order_created", table_name="order_items")