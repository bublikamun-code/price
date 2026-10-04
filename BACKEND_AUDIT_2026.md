# BACKEND AUDIT (фактическое состояние) — `/data/Project/price/apps/api`

Дата аудита: фактическое чтение кода. Ничего не выводится из доков — только то, что есть в репозитории.

Масштаб: **22 модели / 35 таблиц**, **162 эндпоинта** (v1=115, v2=46 + health/miniapp), **29 сервисов**, **18 репозиториев**, **10 Celery-модулей**, **28 миграций**, **61 test-файл / 472 тест-функции**.

---

## 1. Структура

**Models** — `apps/api/app/models/`
- `user.py` (User, Session, TotpRecoveryCode, ConsentLog, PasswordResetToken, Favorite)
- `organization.py` (Organization, OrganizationMembership, OrganizationPricingAgreement, OrganizationBrandTerm, OrganizationAddress)
- `catalog.py` (Brand, BrandVolumeTier, Series, Product, ProductPhoto, PriceListVersion, PriceHistory)
- `pricing.py` (ExchangeRate, UserBrand)
- `order.py` (Cart, CartItem, Order, OrderItem, OrderIdempotency)
- `invoice.py` (Invoice) · `file.py` (FileAsset, MediaAsset) · `system.py` (AuditLog, Notification, NotificationReadState) · `news.py` · `banner.py` · `enums.py`
- Импорт всех моделей централизован в `models/__init__.py` (регистрация в `Base.metadata` для Alembic).

**Routers** — `apps/api/app/api/`
- **v1** (`/api/v1`): `auth.py`(17), `orders.py`(8), `catalog.py`(8), `manager/{users,products,prices}(7+7+7)`, `public.py`(6), `cart.py`(6), `manager/{brands,banners}(5+5)`, `notifications.py`(4), `manager/news.py`(4), `manager/{orders,files,currencies}(3×3)`, `files.py`, `favorites.py`, `admin.py`, `news.py`, `banners.py`, `dashboard.py`, `manager/{dashboard,audit}`(1+1), `integrations/one_c.py`(4)
- **v2** (`/api/v2`, RFC-9457 Problem Details): `auth.py`(6), `organizations.py`(5+manager-subrouter), `orders.py`(5), `cart.py`(5), `volume_tiers.py`(4), `documents.py`(4), `catalog.py`(4), `addresses.py`(4), `invoices.py`(2+manager-subrouter), `session.py`(2), `media.py`(1), + `errors.py`/`pagination.py` (не роутеры)
- Вне версионирования: `api/miniapp.py` (`/api/m/v1/auth/telegram`), `api/v1/health.py` (`/healthz`, `/readyz` на root)

**Services** — `apps/api/app/services/` (29 файлов): `auth.py`(806), `order.py`(782), `organizations.py`(562), `invoice.py`(509), `manager_catalog.py`(459), `pricing.py`(443), `cart_v2.py`(310), `manager_users.py`(306), `export.py`(295), `client_dashboard.py`(259), `volume_tiers.py`(239), `file_assets.py`(327), `email.py`(224), `price_changes.py`(205), `cache.py`(199), `telegram_auth.py`(198), `media.py`(177), `cart.py`(186), `storage.py`(229), `dashboard.py`(141), `photo_zip.py`(126), `admin_users.py`(140), `public_catalog.py`(98), `notification_events.py`(87), `notifications_feed.py`(80), `banner.py`(81), `favorite.py`(74), `news.py`(69), `product_export.py`(58), `currency.py`(49), `notifications.py`(50), `auth_v2.py`(31)

**Repositories** — `apps/api/app/repositories/` (18 файлов, 3442 строки): `catalog.py`(668), `organizations.py`(388), `manager_catalog.py`(316), `orders.py`(274), `notifications.py`(221), `dashboard.py`(196), `users.py`(193), `cart.py`(185), `file_assets.py`(179), `price_changes.py`(127), `public.py`(116), `volume_tiers.py`(107), `news.py`(84), `audit.py`(71), `favorites.py`(68), `rates.py`(67), `invoices.py`(66), `admin.py`(60)

**Celery** — `app/workers/__init__.py` (app `Celery(...)`) + `app/tasks/`: `import_price_list`, `notifications`, `email`, `export_catalog`, `export_order_pdf`, `export_invoice_pdf`, `export_products_full`, `photo_zip`, `fetch_nbrb_rates`, `automation`, `_common`

**Прочее**: `app/importers/{csv_price,optibox}.py` (чистые парсеры), `app/integrations/one_c/` (client/http_client/stub/factory), `app/schemas/commerceml/` (CommerceML DTO), `app/core/` (config, security, deps, limiter, logging, metrics, http_metrics, problem_errors, sanitize, templates), `app/scripts/` (13 скриптов: seed, импортёры Keaz/Rostok/SW, фото-пайплайн, `check_v2_semantics.py`, `export_v2_contract.py`).

---

## 2. Полнота модели данных

**Существует:**
- **User** (`users`) — `email CITEXT unique`, `password_hash`, `full_name`, `company`, `phone`, `role` (CLIENT/MANAGER/ADMIN), `is_active`, `consent_accepted_at`, `display_currency`, `fixed_rate_id`, `totp_secret`, `telegram_id`, `active_organization_id`, `price_digest_enabled/sources`, `must_change_password`
- **Session** (`sessions`) — `refresh_token_hash unique` (opaque refresh, SHA-256), `user_agent`, `ip`, `expires_at`, `revoked`, `rotated_at`, `superseded_by_hash`, `client_type/device_name/os_name/app_version` → полноценный session management
- **Organization** — `legal_name`, `tax_id` (УНП), `country_code`, `default_currency`, `legal_address/email/phone`, `bank_name/bank_code/bank_account`, `version` ( optimistic locking)
- **OrganizationMembership** — `role` (OWNER/BUYER/CONTACT/VIEWER), `is_active`, `is_primary`, `version`
- **OrganizationPricingAgreement** — `display_currency`, `fixed_rate_id`, `agreement_reference`
- **OrganizationBrandTerm** — per-org per-brand `discount_percent` ← **скидки по договору**
- **OrganizationAddress** — `kind`, `label`, `recipient_name`, `phone`, `address_line`, `city`, `postal_code`, `country_code`, `is_default`
- **Brand / Series / Product** — Brand: `slug unique`, `version`; Series: `name`, `brand_id`, `photo_key`; Product: `sku`, `name`, `series_id`, `brand_id`, `base_price Numeric(12,2)`, `override_price`, `stock_status`, `stock_qty`, `price_list_version_id`, `deleted_at` (soft delete), `attributes JSONB`
- **ProductPhoto**, **ProductPrice→PriceHistory** (`base_price`/`override_price`/`price_list_version_id`/`changed_at`)
- **PriceListVersion** — `filename`, `import_mode` (UPSERT/REPLACE/ARCHIVE_MISSING), `status` (QUEUED/PROCESSING/DONE/FAILED), `rows_total/ok/error`, `error_log_key`, `base_currency`, `rate_to_byn`, `rate_source`, `started_at/finished_at`, `rolled_back_at/by` → **импорт-джоб + откат**
- **UserBrand** — per-user per-brand `discount_percent` (личные цены)
- **BrandVolumeTier** — `min_qty` + `discount_percent`, `version` → **скидки за объём**
- **ExchangeRate** — `currency_code`, `rate Numeric(12,4)`, `scale`, `fetched_at`, `source`, `is_manual` → валюты + ручные курсы
- **Cart / CartItem** — Cart: `user_id`, `organization_id`, `version`, `name`; CartItem: `product_id`, `quantity`, `note`
- **Order** — `client_id`, `organization_id`, `manager_id`, `status`, `currency_code`, `exchange_rate`, `rate_source`, `total_amount`, структурированная доставка (`delivery_method/point/address/address_id/contact_name/phone/preferred_date/comment`), `external_id` (1С), `seq`, `version`
- **OrderItem** — `product_snapshot JSONB` (замороженный SKU/name/brand), `quantity`, `unit_price` (заморожена), `currency_code`, `note`
- **OrderIdempotency** — `user_id`, `idempotency_key`, `request_hash`, `order_id`
- **Invoice** — `order_id UNIQUE`, `seq`, `number`, `status` (ISSUED/PAID/CANCELLED), `pdf_status` (PENDING/READY/FAILED), `pdf_file_asset_id`, `total_amount`, `currency_code`, `issued_at`, `due_at`, `created_by`, `version`
- **FileAsset** — `type` (BRAND_PDF/CUSTOM_CSV/PHOTO_ZIP/CERTIFICATE/DATASHEET/INVOICE_PDF/OTHER), `visibility` (PUBLIC/AUTHED/MANAGER_ONLY), `brand_id/product_id/series_id/order_id`, `valid_until`, `size_bytes`
- **MediaAsset** — `width/height/mime_type` (стабильные media-ID вместо presigned-URL)
- **Notification + NotificationReadState** — `user_id` (NULL = broadcast), `type/title/body/payload/channel`, `is_read`; `notification_reads(notification_id, user_id, read_at)` — персональные прочтения broadcast
- **AuditLog** — `actor_id`, `action`, `target_type/target_id`, `before/after JSONB`
- **ConsentLog**, **PasswordResetToken**, **TotpRecoveryCode**, **Favorite**, **News**, **Banner**

**ОТСУТСТВУЕТ (подтверждено grep'ом по всему `app/`):**
- **VAT / налоги** — ABSENT полностью (нет ни колонки, ни схемы, ни расчёта)
- **Единицы измерения (UoM)** — ABSENT (quantity — безразмерный `Integer`)
- **Склады** — ABSENT как сущность; остаток — один глобальный `products.stock_qty` + enum `StockStatus` на 2 значения (`IN_STOCK`/`PREORDER`) + `ARCHIVED`. `Warehouse` существует только как CommerceML DTO (`app/schemas/commerceml/common.py:60`) для приёма остатков из 1С
- **Категории товаров** — ABSENT; таксономия = Brand → Series. Строка «category» встречается только как аналитическая метка в дашборде (`schemas/dashboard.py:65`) и как свободный JSONB в `attributes`
- **Возвраты / RMA** — ABSENT
- **Условия оплаты, отсрочка, кредитный лимит, долг** — ABSENT
- **Назначение менеджера клиенту** — ABSENT: `orders.manager_id` — nullable free-form, ставится вручную при смене статуса (`services/order.py:745`, `repositories/orders.py:268`); нет таблицы назначений, нет авто-роутинга, менеджер видит все заявки без скоупа
- **Сущность «прайс-лист» как объект** — ABSENT: цена = `override_price` + per-user/per-org скидка по бренду + `BrandVolumeTier`. Нет сущности PriceList, нет привязки прайс-листа к клиенту, нет срока действия цены

---

## 3. Бизнес-логика (что сверх CRUD)

- **`services/pricing.py`** — ядро: приоритет цены `override_price` → `base_price*(1-discount%)` → `base_price`; объёмная скидка как **max(бренд-скидка, ступень объёма)** (не суммируются, `override_price` не подвержена); выбор org-brand-term → user-brand → retail; конвертация валюты по `rate/scale`; единая точка округления `quantize_money` (2 знака, ROUND_HALF_UP) и `quantize_rate` (4 знака)
- **`services/order.py`** (782) — FSM `NEW→IN_PROGRESS→SHIPPED→COMPLETED` + `CANCELLED` из любого незавершённого (`ALLOWED_TRANSITIONS:43`); **заморозка** `unit_price`/`exchange_rate` при оформлении; идемпотентность через `OrderIdempotency` + `request_hash`; доменные ошибки с машинными кодами
- **`services/organizations.py`** — резолв активной организации **только** через явную membership (не выводится из `User.company`); `can_access`; CRUD участников с audit; адресный бук с `_require_writer`
- **`services/invoice.py`** — инвариант 1:1 с заказом (второй → 409 `INVOICE_ALREADY_EXISTS`, заказ `CANCELLED` → 409 `ORDER_NOT_INVOICABLE`); заморозка сумм; идемпотентность выдачи; регенерация PDF; биллинг-данные организации; **платёжного ledger нет** — статус счёта переключает менеджер вручную (комментарий `enums.py:45`)
- **`services/volume_tiers.py`** — ступень как самостоятельный ресурс с собственной `version`; `If-Match` сверяет версию **ступени**, а не бренда
- **`services/price_changes.py`** — классификация изменений версии прайса (`new/up/down/override_reset/unchanged`) + подбор получателей дайджеста по корзине/избранному/заказам (opt-in)
- **`services/price_list_import.py`** — приём CSV в S3 `tmp-uploads`, создание `PriceListVersion(QUEUED)`, dispatch Celery, **откат версии**
- **`importers/csv_price.py`** — чистый конвертер: алиасы колонок (RU/EN, 30+ заголовков), `pl.read_csv`, нормализация строки → `NormalizedRow | RowError`, опциональный `stock_qty`
- **`importers/optibox.py`** — отдельный маппинг выгрузки 1С-Битрикс (коды `IP_PROP*`/`IE_*`/`CV_*`)
- **`services/auth.py`** (806) — login с веткой 2FA, refresh с **rotation + grace-периодом**, logout, TOTP setup/enable/verify/disable, recovery codes, журнал сессий + revoke one/all, password reset, `must_change_password`, login Mini App
- **`services/cache.py`** — Redis-кэш с **теговой инвалидацией** (`CATALOG_TAG`, `FILTERS_TAG`, `VOLUME_TIERS_TAG`), fail-open (недоступный Redis не ломает эндпоинт)
- **`services/notifications*.py`** — сборка текстов из Jinja2 (`app/templates/notifications/*.j2`), Redis Pub/Sub + SSE (`notification_events.py`), pull-лента с персональными прочтениями
- **`services/manager_users.py` / `admin_users.py`** — temp-пароль при создании менеджера, блокировка с немедленным отзывом сессий
- **`services/file_assets.py`** — валидация расширения/content-type/**magic-bytes**/размера стримингом по чанкам, заливка в S3 стримингом
- **`services/media.py`** — детерминированный `/api/v2/media/{mediaId}` вместо 5-минутных presigned URL (для стабильности нативного кэша)
- **Audit:** `repositories/audit.py` пишет before/after; вызывается из `auth, admin_users, manager_users, manager_catalog, organizations, invoice, currency, volume_tiers`

---

## 4. Auth & безопасность

- **Хэширование**: `bcrypt` cost=12; async-обёртки через `run_in_threadpool` (`core/security.py:39-50`) — блокировка event loop явно устранена
- **JWT**: PyJWT; `JWT_ALGORITHM` = HS256 (dev) / **RS256** (prod, PEM из `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, `make gen-jwt-keys`); типы токенов строго разделены — `access` / `refresh` / `2fa` (ticket 5 мин, только `sub`); `access_token_ttl_min=15`, `refresh_token_ttl_days=7`, `refresh_grace_seconds=60`
- **Refresh**: opaque random string, в БД только SHA-256 хэш (`sessions.refresh_token_hash unique`); ротация + `rotated_at`/`superseded_by_hash`
- **Транспорт**: httpOnly-cookie для web (v1) и bearer в теле ответа для нативного клиента (v2) — `services/auth_v2.py`; CSRF через `X-CSRF-Token` + double-submit (`deps.validate_csrf:53`)
- **RBAC**: 3 роли (`UserRole` CLIENT/MANAGER/ADMIN) + 4 роли внутри орг-контракта (`OrganizationRole` OWNER/BUYER/CONTACT/VIEWER). Хелперы `require_role(*roles)`, `require_admin`; per-organization проверки через `OrganizationResolver.can_access`. `require_role` используется 87 раз. Отдельной permission-матрицы (granular permissions/scopes) НЕТ — только role checks
- **Rate limiting**: slowapi + Redis (`core/limiter.py`); `login 5/15min`, `forgot_password 5/15min`, `invoice_issue 10/hour`, экспорт `10/hour` (ключ по user-id из JWT, fallback IP), публичный каталог `60/min`; дополнительно `login_max_attempts=5` + `login_lockout_minutes=30`
- **2FA**: полноценный TOTP (pyotp) — setup/enable/verify/disable + `TotpRecoveryCode` (одноразовые, хэш)
- **Мини-приложение**: `api/miniapp.py` — верификация `initData` подписью бота (`_verify_init_data`)
- **Middleware**: CSRF, RequestContext (X-Request-ID с whitelist-регексом, structlog contextvars), SecurityHeaders (nosniff, X-Frame-Options DENY, Referrer-Policy, COOP, HSTS, CSP, Permissions-Policy, Cache-Control no-store при cookie), MaxBodySize (1 МБ JSON, multipart не трогается), Prometheus, CORS (явный список методов/заголовков)
- **Отсутствует:** email-верификация адреса (нет `email_verified_at`, нет verify-эндпоинта; `forgot-password`/`reset-password` есть, но без доказательства владения почтой); нет `ip_allowlist`/`device trust`/гео-ограничений; нет токенов API для машинных интеграций; нет brute-force учёта по паре (email+IP).

---

## 5. Миграции

- **28 файлов** в `apps/api/alembic/versions/`; **единственный head = `0025_add_missing_indexes`** — цепочка линейная и непрерывная
- Порядок: `0001_initial` → `0002` → `0003` → `47c20b0f969c` → `863ddb771b92` → `0004_add_news` → `c4f9a2b71d3e` → `0005…0025`
- Имена неоднородны (номерные `00NN_*` vs hash-идентификаторы) — следствие перехода со `alembic revision --autogenerate`
- **Есть отдельные «починки» дрейфа**: `0007_sync_models_drift`, `0017_reconcile_model_constraints`, `0018_fix_constraint_drift` — то есть дрейф моделей↔схема фиксировался постфактум, а не превентивно
- Покрытие миграциями полное: 0023 Invoice, 0024 volume tiers, 0020 MediaAsset, 0021 product documents, 0022 broadcast reads, 0025 индексы
- Тест на согласованность: `tests/test_rollback.py`, `tests/test_architecture_boundaries.py`

---

## 6. Тесты

- **61 файл** `apps/api/tests/test_*.py`, **472 тест-функции**, `pytest.ini` (`asyncio_mode=auto`, `--strict-markers`)
- Запуск: `make test` (через docker exec в контейнер `api`, авто-создание БД `<db>_test`) или `make test-pattern T="tests/test_catalog.py -k discount"`
- `conftest.py`: session-scope engine на `TEST_DB_URL`, `create_user/brand/series/product`, `set_discount/set_rate/set_fixed_rate_for_user/set_display_currency`, `create_organization/add_organization_membership/set_active_organization/set_organization_pricing_agreement/set_organization_brand_term`, `api_client`
- Покрытие: v1 (auth, catalog, cart, orders, files, favorites, notifications, dashboard, admin, manager_*), **v2 (auth, addresses, cart, invoices, media, orders+actions+create, organizations, product documents, volume tiers)**, pricing, volume tiers, CSV import + reliability, OptiBox import, 1C integration, JWT RS256, TOTP/2FA, force-password-change, consent, cache, sanitize, health/readyz, prod-config guard, rollback, notification dispatch idempotency, photo zip, exports, email templates, miniapp/telegram auth, one rounding (`test_decimal_money`), архитектурные границы
- Нагрузочные: `make test-load` (k6, каталог 100 RPS), `make test-load-import` (импорт 50k строк)
- Отсутствует: e2e-тестов бэка нет; покрытие самих `repositories/*.py` опосредованное (через API)

---

## 7. Фоновые задачи и интеграции

**Celery-задачи (`app/tasks/`):**
| Задача | Назначение |
|---|---|
| `import_price_list.run_import` | импорт CSV → товары/цены/остатки, rows_ok/error, error_log_key |
| `import_price_list.reconcile_stuck_imports` | (beat) возврат зависших PROCESSING-импортов в FAILED |
| `app.tasks.notifications.dispatch_price_changed` | сбор получателей + рассылка (Redis-lock против повторной отправки) |
| `app.tasks.notifications.send_telegram` | доставка в Telegram-чат |
| `app.tasks.email.send_email` | реальная SMTP-отправка |
| `export_catalog.run_export` | каталог CSV/XLSX/PDF |
| `export_order_pdf.run_order_pdf` | PDF заявки |
| `export_products_full.run_full_export` | полный экспорт продукции (CSV) |
| `render_invoice_pdf` | PDF счёта (колонка `invoices.pdf_status`) |
| `photo_zip.run_photo_zip` | ZIP фото серий → WebP, S3 |
| `app.tasks.fetch_nbrb_rates.fetch_rates` | (beat, 00:05 Europe/Minsk) курсы НБ РБ + fallback-алерт |
| `automation.run_automation` | общая заглушка/обёртка |

Beat: `fetch_nbrb_rates`, `metrics_push_queue_depth`, `reconcile_stuck_imports`.

**Email**: `services/email.py` рендерит письма (Jinja2) и диспатчит Celery `send_email`; SMTP-настройки полные (host/port/user/pass/from, STARTTLS-флаг, `manager_notify_email`). Явно задокументировано, что раньше `queue_email` был no-op. Email-верификация НЕ реализована — SMTP используется только для сброса пароля и уведомлений.

**Telegram-бот**: рабочий (`app/bot/__main__.py`, long polling, `python -m app.bot`, отдельный контейнер). Команды: `/start <код>` (привязка аккаунта), `/unlink`, `/id`, `/help`. `services/telegram_auth.py` — генерация кода привязки в профиле + `bind_by_code`. Отдельные Mini App auth (`/api/m/v1/auth/telegram`).

**S3 / RustFS**: `services/storage.py` (sync boto3, бакеты `tmp-uploads`, `pdf-catalogs`), streaming-загрузки в `file_assets.py`, `price_list_import.py`, `photo_zip.py`; presigned-URL для скачивания; `check_connection` в `/readyz`.

**1С**: `app/integrations/one_c/` — `HttpOneCClient` + `StubOneCClient`, выбор в `factory.py` по конфигурации (приложение стартует всегда). Эндпоинты `/api/integrations/1c/**` (4): `orders/export`, `prices/import`, `stock/import`, `orders/status`. CommerceML-схемы: `prices.py`, `orders.py`, `stock.py`, `common.py`. **Реального обмена с живой 1С нет — по умолчанию stub (503/501).**

---

## 8. Observability & ops

- **Логирование**: `structlog` → JSON в prod, цветной ConsoleRenderer в dev; processors: contextvars merge, add_log_level, ISO-таймстемпер, StackInfo, exc_info; корреляция через `RequestContextMiddleware` (`X-Request-ID` с безопасным whitelist-регексом, эхо в ответе)
- **Метрики**: Prometheus; собственный ASGI-middleware `core/http_metrics.py` (`http_request_duration_seconds`, `http_requests_total`) — `prometheus-fastapi-instrumentator` удалён из-за несовместимости со starlette 0.5x; `/metrics` отдаёт `generate_latest()`, в prod — 404 без корректного `X-Metrics-Token` (сравнение через `hmac.compare_digest`)
- **Health**: `/healthz` (liveness, без БД) и `/readyz` — 200 только если живы **БД + Redis + S3**, иначе 503 с перечнем `checks`; окружение наружу не светится (anti-fingerprinting)
- **Error handling**: 4 exception handler'а — `V2ProblemError`→RFC-9457, `StarletteHTTPException` (диспетчер по `is_v2_request`), `RequestValidationError` (v2→Problem Details, v1→стандартный), глобальный `Exception` (лог `unhandled_error` + единый конверт `APIError/ErrorResponse` для v1, Problem Details для v2); `RateLimitExceeded` → 429 `RATE_LIMITED` c `Retry-After`; `core/problem_errors.py` + `core/sanitize.py`
- **Версионирование API**: v1 (`/api/v1`, legacy-конверт `{detail}`/`APIError`) + v2 (`/api/v2`, RFC-9457, cursor-пагинация, `If-Match` оптимистичная блокировка, `Idempotency-Key`) — **v1 не удалён**, дублирование контрактов
- **OpenAPI**: `/docs`, `/redoc`, `/openapi.json`; **полностью отключаются при `env=prod`**. Скрипт `app/scripts/export_v2_contract.py` выгружает зафиксированный контракт; тест `test_contract_artifacts.py` проверяет его совпадение с текущими схемами; `check_v2_semantics.py` валидирует подмножество правил совместимости
- **Ops**: k6-нагрузочные сценарии в Makefile, `docker-compose.prod.yml` скрывает порт API, Prometheus/Grafana-совместимые имена метрик сохранены

---

## TOP GAPS (backend) — 15

1. **VAT / налоги — ABSENT**: ни колонки, ни схемы, ни расчёта; все суммы брутто без налоговой разбивки.
2. **Склады — ABSENT**: единственный глобальный `products.stock_qty` + `StockStatus` на 2 значения; нет остатков по складам/точкам, нет резерва под заказ.
3. **Единицы измерения — ABSENT**: `quantity` безразмерный `Integer`, нет UoM/кратности/упаковки.
4. **Категории товаров — ABSENT**: таксономия только Brand→Series; «категория» существует лишь как JSONB и как аналитическая метка.
5. **Возвраты / RMA — ABSENT**: нет ни модели, ни эндпоинтов, ни статуса заказа `RETURNED`.
6. **Условия оплаты, отсрочка, кредитный лимит, долг — ABSENT**: денежных обязательств в модели нет вообще.
7. **Назначение менеджера клиенту — ABSENT**: `orders.manager_id` ставится вручную, таблицы назначений нет, менеджер видит все заявки без скоупа.
8. **Approval/согласование заявки — ABSENT**: FSM линейный `NEW→IN_PROGRESS→SHIPPED→COMPLETED`; нет подтверждения клиентом, переторга, котировки (quote) и конвертации в заказ.
9. **Сущность «прайс-лист» — ABSENT**: цена = `override_price` + per-user/per-org скидка + объёмные ступени; нет PriceList-объекта, привязки к клиенту, срока действия цены и ценовых серий.
10. **Платёжный ledger — ABSENT**: `InvoiceStatus` переключается менеджерем вручную (признано в `enums.py:45`); частичная оплата, аванс, акт сверки отсутствуют.
11. **Email-верификация — ABSENT**: `forgot/reset-password` есть, доказательства владения адресом нет; `is_verified` в модели отсутствует.
12. **Метрики Celery — заглушки**: `app/core/metrics.py` целиком `pass`; `record_task_duration/record_task_failure/push_worker_metrics` ничего не пишут, `pushgateway_url` не используется — фоновые задачи не наблюдаемы.
13. **RBAC без гранулярных прав**: только 3 глобальные роли + 4 роли в орг-контракте; пермиссий/скоупов на уровне ресурса нет, все проверки — ролевые.
14. **Дублирование API-контрактов**: v1 (115 эндпоинтов) и v2 (46) живут параллельно, `/api/v1` не объявлен deprecated — двойная поддержка и риск расхождения логики.
15. **Покрытие прямых e2e/нагрузки бэка минимально**: 472 теста — в основном API-уровневые; нагрузка только k6-сценариями вручную, тестов Celery-воркеров, S3 и реального SMTP в CI нет.

---

*Дополнительно (вне TOP-15, для контекста):* реального обмена с 1С нет — только `StubOneCClient`; `tests` требуют запущенного Postgres (`TEST_DB_URL`), быстрых unit-тестов чистых модулей без БД нет; Alembic-имена миграций неоднородны, а `0007/0017/0018` — заплатки дрейфа моделей↔схемы.