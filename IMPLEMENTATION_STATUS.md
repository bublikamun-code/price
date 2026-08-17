# Статус исправлений аудита

Источник: вставленный отчёт аудита этапов 0–5. Проверено относительно текущего кода и канона `ARCHITECTURE_PLAN.md` (§6, §11; документ читался поиском по секциям).

## Классификация

| Пункт | Статус | Результат |
|---|---|---|
| Refresh доступен JavaScript | ✅ исправлено | Удалён из JSON-контракта, Pinia и frontend-cookie; refresh/rotation только через httpOnly cookie. |
| Logout не удаляет cookies | ✅ исправлено | Ответ удаляет access/refresh cookies; сессия отзывается. |
| Upload читает весь файл до лимита | ✅ исправлено частично | Чтение ограничено `limit + 1`; полный streaming в S3 остаётся отдельной задачей. |
| Валюта обрезается до 3 символов | ✅ исправлено | Строгая проверка ровно трёх латинских букв, иначе 422. |
| CSRF для cookie auth | ⏳ актуально | Требует отдельного согласованного внедрения double-submit во все mutating-запросы и frontend. |
| HS256/default secret вместо RS256 | ✅ исправлено (2026-08-16) | Схема §16 п.15 (v1.3): dev HS256+SECRET_KEY, prod RS256 с PEM-ключами read-only (`JWT_*_KEY_PATH`); fail-fast валидация на старте, `make gen-jwt-keys`, prod-compose обновлён. |
| SQL в роутерах | ✅ исправлено (2026-08-16) | `manager/prices`: оркестрация импорта → `services/price_list_import.start_import`; `catalog`: `select(Brand/Series)` → `repositories/catalog.get_brand/get_series`. В `api/v1` прямой ORM остался только в `health.py` (SELECT 1, healthcheck). |
| Каталог vs §6, response envelopes | ⏳ требует отдельной сверки | Контракт объёмный; не менялся без полного endpoint-by-endpoint решения. |
| ILIKE вместо FTS/pg_trgm | ⏳ актуально | Подтверждено в `repositories/catalog.py`. |
| N+1 каталога | ⏳ требует профилирования | Старый отчёт недостаточен как доказательство после изменений кода. |
| Upload только по расширению | ✅ исправлено | До S3 проверяются allowlist MIME, UTF-8/BOM, отсутствие NUL и обязательный CSV-заголовок `sku`/`name`; политика зафиксирована в §7.1. |
| UUID v4 вместо v7 | ⏳ требует миграционного решения | Изменение идентификаторов затрагивает модели/БД/совместимость. |
| README устарел | ✅ подтверждено | Manager import и product page уже существуют; дорожная карта требует обновления после завершения текущего пакета. |
| Production TLS | ⏳ runtime/deployment | Нельзя подтвердить статическим кодом без окружения. |
| Redis rate limiter | ✅ исправлено | slowapi использует общее Redis-хранилище счётчиков, URL собирается из `REDIS_HOST/PORT/DB`; покрыто конфигурационными тестами. |
| Dead code, schema drift | ⏳ отдельный аудит | Требуют отдельной ограниченной сверки; не смешивались с rate-limiter пакетом. |

## Пакет 2026-08-17 (3): файловый архив (Этап 7-остаток, §16 п.18)

- Канон-first (§21): §16 п.18 — детали контракта (visibility-права CLIENT→PUBLIC/AUTHED, фильтры type/brand_id, лимит 200 МБ `FILES_MAX_MB`, magic-bytes %PDF/PK, ключ `{type}/{uuid}{ext}` в бакете `pdf-catalogs`, download presigned TTL 5 мин, DELETE сначала S3 → потом БД).
- Backend: `schemas/file.py` + `repositories/file_assets.py` + `services/file_assets.py` (валидация, стриминг) + `GET /files`, `GET /files/{id}/download`, `POST/GET/DELETE /manager/files`; `storage.delete_object`; `files_max_mb=200`. Модель `file_assets` существовала (миграция 0001) — новых миграций нет.
- Frontend: `pages/files.vue` (фильтры тип/бренд, таблица, скачивание), `pages/manager/files.vue` (dropzone ≤200 МБ, тип/видимость/бренд, удаление с confirm), типы в `types/api.ts`; бренды — из `GET /catalog/filters`.
- Исправление (найдено GUI-тестом): `storage.presigned_get` переписывал хост строкой после генерации подписи → `SignatureDoesNotMatch` на ВСЕ presigned-ссылки (экспорт, логи ошибок). Фикс: отдельный клиент `get_s3_presign_client` на `s3_external_endpoint` (host входит в SigV4; `generate_presigned_url` сети не требует, безопасно из контейнера).
- Инфра-починки dev-стенда: пересобран runtime-образ worker/beat (Pillow, §16 п.17); рестарт nginx (устаревший IP api); клиент фронтенда переведён на same-origin через nginx — `NUXT_PUBLIC_API_BASE=""` в compose + `??` вместо `||` в `nuxt.config.ts` (единый вход §14).
- Проверки: pytest — все зелёные (+20 `test_files.py`), ruff чисто, web typecheck/eslint — 0 ошибок. GUI (browser-use): логин менеджером, обе страницы, фильтры, скачивание (presigned → 200, файл открывается), удаление; загрузка через GUI не проверялась (IAB-вебвью не поддерживает file chooser) — покрыта API-загрузкой и pytest.
- Известные остатки (вне пакета): перелогин с остаточными cookie `access_token`/`refresh_token` без CSRF-заголовка → 403 без понятного сообщения (UX-дефект `validate_csrf`); `pp-bot` циклически рестартует (`python -m app.bot` — нет `__main__.py`).

## Изменённые файлы

- `apps/api/app/api/v1/auth.py`
- `apps/api/app/schemas/auth.py`
- `apps/api/app/api/v1/manager/prices.py`
- `apps/api/tests/test_import_csv.py`
- `ARCHITECTURE_PLAN.md`
- `apps/api/tests/test_auth.py`
- `apps/api/app/core/config.py`
- `apps/api/app/core/limiter.py`
- `apps/api/tests/test_health.py`
- `apps/web/composables/useAuth.ts`
- `apps/web/plugins/auth.session.ts`
- `apps/web/types/api.ts`
- `IMPLEMENTATION_STATUS.md`

## Последний пакет: Redis-backed rate limiter

- Канон: в `ARCHITECTURE_PLAN.md` §11 уточнено общее Redis-хранилище счётчиков между API workers.
- Реализация: `Settings.redis_url` собирает URL из существующих `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`; slowapi использует этот URL вместо process-local memory storage.
- Тесты: `apps/api/tests/test_health.py` проверяет сборку Redis URL и Redis backend limiter-а без подключения к production-инфраструктуре.
- Миграции, новые секреты и продуктовые решения не требуются.

## Пакет 2026-08-16: SQL из роутеров (§4)

- Канон §4: роутеры тонкие («только HTTP»), use-case'ы в `services/`, DAO в `repositories/`.
- `manager/prices`: use-case импорта (создание `PriceListVersion` → streaming в S3 → rollback при `StorageError` → commit → dispatch Celery) вынесен в `services/price_list_import.py`; роутер — HTTP-валидация и маппинг `StorageError` → 502.
- `catalog`: прямые `select(Brand)`/`select(Series)` в `get_product` заменены на `repositories/catalog.get_brand/get_series`.
- `db.commit()` в cart/favorites/orders-роутерах сохранён — согласованный UoW-паттерн проекта (транзакцию коммитит владелец запроса), не долг.
- Проверки: 159 passed (`make test`, docker), ruff по изменённым файлам — чисто (3 предсуществующих E702 в `tests/test_cache.py` не тронуты), compileall exit 0.

## Пакет 2026-08-17 (2): photo-ZIP — фото серий, webp-миниатюры, series_photo (Этап 4-остаток, §16 п.17)

- Канон v1.5: §6 (`POST /manager/prices/photo-zip` + `GET /{job_id}`, `GET /files/photo` → 307), §10 (конвенция ключей `{slug}.webp`/`{slug}_thumb.webp`, матчинг), §16 п.17 (лимиты ZIP ≤100 МБ / распаковано ≤500 МБ / ≤2000 файлов / файл ≤50 МБ).
- Backend: `services/photo_zip.py` + `tasks/photo_zip.py` (Pillow webp 400/1200 fit q82; zip-bomb guard: лимиты по заголовкам + capped-read; матчинг stem→slug, приоритет — «сырое» photo_key из CSV; unmatched-фото заливаются); импорт CSV: `series_photo` → `series.photo_key` (закрыт нереализованный §7-пункт); `GET /files/photo?key=` → 307 presigned (валидация ключа без `..`/схемы).
- Инфра: Pillow==11.2.1, api-образ пересобран (webp ✓).
- Frontend: dropzone ZIP на странице импорта (опрос job, счётчики matched/unmatched/errors); `useProductPhoto` — S3-ключи через `/files/photo` 307, `thumbOf` для карточек каталога.
- Проверки: 202 passed (+15: 14 photo-zip + 1 series_photo), ruff/compileall чисто, web typecheck 0, eslint 0.
- Выполнено агентом до лимита + доведено вручную: пересборка образа, фикс сломанной строки `versions`-ref в import.vue, дописан UI-блок ZIP и очистка таймера.

## Пакет 2026-08-17: экспорт каталога CSV/XLSX (Этап 7, §16 п.16)

- Решения заказчика (§21): метод POST (расхождение §6-GET/SITEMAP-POST устранено), форматы CSV+XLSX сейчас / PDF отложен (422). Канон v1.4: §6, §16 п.16.
- Backend: `services/export.py` (job-стейт Redis `export:job:{id}`, TTL 24 ч, fail-open), `tasks/export_catalog.py` (RUNNING→DONE/FAILED, CSV utf-8-sig «;», XLSX openpyxl, upload в `csv-exports`), `repositories/catalog.fetch_catalog_all` (+ общий `_apply_catalog_filters` для списка/счётчика/экспорта), роутеры `POST /catalog/export` (rate-limit 10/час, ключ — user из JWT) и `GET /catalog/export/{job_id}` (владелец-only, presigned 5 мин).
- Frontend: каталог — кнопка «Экспорт» (CSV/XLSX) с текущими фильтрами, опрос job каждые 2 с (макс. 60), скачивание по url.
- Проверки: 187 passed (+9 `test_export.py`), ruff/compileall чисто, web typecheck — 0. Починен шум «Event loop is closed» на выходе pytest (тест без мока redis-клиента открывал реальное соединение → autouse FakeRedis в модуле).
- Примечание: PDF-экспорт — отдельная задача (weasyprint + системные deps в образ, см. §16.1 F).

## Пакет 2026-08-16 (2): rollback версии прайса (Этап 9, §16 п.14)

- Канон-first (§21): §16 п.14 (семантика: восстановление цен из `price_history` + архивация новых товаров; откат только последней DONE-версии, иначе 409), §5 (`rolled_back_at/by`), §6 (контракт эндпоинта); документ поднят до v1.2. Семантика согласована с заказчиком в сессии.
- Backend: миграция `47c20b0f969c` (применена к dev-БД); `repositories/catalog.rollback_version` — set-based SQL (restore через `DISTINCT ON` с push-down по товарам версии + архивация через `NOT EXISTS`); `services/price_list_import.rollback_version` — FOR UPDATE, гварды, commit + инвалидация `CATALOG_TAG/FILTERS_TAG`; роутер `POST /manager/prices/versions/{id}/rollback` → 404/409/200 `RollbackOut{version, restored, archived}`.
- Frontend: `manager/import.vue` — кнопка «Откатить» (только последняя DONE, confirm-диалог), бейдж «Откатена» с датой, сообщение с счётчиками; типы в `types/api.ts`.
- Проверки: 169 passed (`make test`, +10 `test_rollback.py`: happy/409×3/404/403/кэш), ruff по изменённым файлам — чисто, web `npm run typecheck` — 0 ошибок, alembic 1 head.

## Пакет 2026-08-16 (3): RS256 для production JWT (§16 п.15)

- Решение заказчика (§21): PEM-файлы, смонтированные read-only (Vault вне MVP). Канон: §11 уточнён, §16 п.15, v1.3.
- Backend: `config.py` — `jwt_private/public_key_path` + fail-fast `model_validator` (RS256 без ключей/с нечитаемыми файлами → ошибка старта; whitelist HS256/RS256; HS256+пути → warning), свойства `jwt_signing_key`/`jwt_verify_key` с кэшем PEM по пути; `security.py` подписывает/проверяет соответствующим ключом.
- Инфра: `make gen-jwt-keys` (RSA-2048 в `infra/jwt-keys/`, отказ при перезаписи), `.gitignore`, `infra/docker-compose.prod.yml` — env+монтирование ключей для api; попутно исправлен предсуществующий баг: `volumes: []` в override не убирал dev-монтирование исходников → `!override`.
- Тесты: `test_jwt_rs256.py` (9): roundtrip access/refresh, чужой ключ → JWTError, валидации конфига, кэш, HS256-дефолт. Итого 178 passed; ruff/compileall чисто; `docker compose config` для prod проверен.
- Замечание: JWT декодирует только api (deps.py); если включить RS256 глобально через общий `.env`, worker/bot упадут на старте с понятной ошибкой (fail-fast) — при необходимости монтировать ключи и им.

## Проверки

- `python3 -m compileall -q apps/api/app apps/api/tests` — успешно после Redis rate-limiter пакета.
- `python3 -m pytest apps/api/tests/test_health.py -q` — не запущен: `pytest` отсутствует в системном Python.
- `python3 -m ruff check apps/api/app/core/config.py apps/api/app/core/limiter.py apps/api/tests/test_health.py` — не запущен: `ruff` отсутствует в системном Python.
- Frontend typecheck не требуется: frontend в этом пакете не менялся.
- Git commit не создавался; корень не является Git working tree.

## Аудит безопасности и качества кода — 2026-08-14

### Выполнено

- Восстановлена безопасная внутренняя передача refresh_token (cookie rotation без выдачи в JSON)
- Добавлен auth-тест
- Удалены неиспользуемые импорты и типы
- Исправлены расхождения authHeaders и useProductPhoto
- Backend: 137/137 pytest passed
- Alembic: 1 head
- compileall: exit 0
- Frontend typecheck: 0 ошибок
- Исправлен nullable chart: в `apps/web/pages/catalog/[sku].vue` строка 294, v-if дополнен `&& chart`

### Блокер — закрыт (2026-08-14, след. сессия)

- **ESLint 9 / Flat Config — решено.** Причина падения была не в конфиге: `@nuxt/eslint` →
  `eslint-flat-config-utils` использует `Object.groupBy` (появился в Node 21+), а контейнер web
  работал на Node 20 (`TypeError: Object.groupBy is not a function`).
  Решение: базовый образ web поднят до Node 22 (`apps/web/Dockerfile` + `engines.node >=22`),
  контейнер пересобран с чистым `node_modules`. Линтер заработал и выявил накопившиеся
  34 errors (`no-explicit-any`) + 64 warnings — устранены: типизация через `unknown` +
  helper `apps/web/utils/errors.ts` (`getErrorMessage`/`getErrorStatus`), автофикс форматирования.
  Итог: `npm run lint` — 0 problems (exit 0), `npm run typecheck` — 0 ошибок (exit 0).
  ESLint возвращён в пайплайн (`make lint`).
