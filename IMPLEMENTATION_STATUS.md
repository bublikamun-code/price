# Статус исправлений аудита

Источник: вставленный отчёт аудита этапов 0–5. Проверено относительно текущего кода и канона `ARCHITECTURE_PLAN.md` (§6, §11; документ читался поиском по секциям).

## Классификация

| Пункт | Статус | Результат |
|---|---|---|
| Refresh доступен JavaScript | ✅ исправлено | Удалён из JSON-контракта, Pinia и frontend-cookie; refresh/rotation только через httpOnly cookie. |
| Logout не удаляет cookies | ✅ исправлено | Ответ удаляет access/refresh cookies; сессия отзывается. |
| Upload читает весь файл до лимита | ✅ исправлено частично | Чтение ограничено `limit + 1`; полный streaming в S3 остаётся отдельной задачей. |
| Валюта обрезается до 3 символов | ✅ исправлено | Строгая проверка ровно трёх латинских букв, иначе 422. |
| CSRF для cookie auth | ✅ исправлено (2026-08-20) | Double-submit внедрён во все mutating-запросы (§16 п.21): middleware на api + `X-CSRF-Token` на фронте; логин/2FA exempt как неаутентифицированные шаги. Строка устарела — закрыта пакетами 2026-08-20(2) и ca3a929. |
| HS256/default secret вместо RS256 | ✅ исправлено (2026-08-16) | Схема §16 п.15 (v1.3): dev HS256+SECRET_KEY, prod RS256 с PEM-ключами read-only (`JWT_*_KEY_PATH`); fail-fast валидация на старте, `make gen-jwt-keys`, prod-compose обновлён. |
| SQL в роутерах | ✅ исправлено (2026-08-16) | `manager/prices`: оркестрация импорта → `services/price_list_import.start_import`; `catalog`: `select(Brand/Series)` → `repositories/catalog.get_brand/get_series`. В `api/v1` прямой ORM остался только в `health.py` (SELECT 1, healthcheck). |
| Каталог vs §6, response envelopes | ⏳ требует отдельной сверки | Контракт объёмный; не менялся без полного endpoint-by-endpoint решения. |
| ILIKE вместо FTS/pg_trgm | ✅ исправлено (2026-08-25) | pg_trgm GIN-индексы + `_like_escape`; деталь — в пакете 2026-08-26. |
| N+1 каталога | ⏳ требует профилирования | Старый отчёт недостаточен как доказательство после изменений кода. |
| Upload только по расширению | ✅ исправлено | До S3 проверяются allowlist MIME, UTF-8/BOM, отсутствие NUL и обязательный CSV-заголовок `sku`/`name`; политика зафиксирована в §7.1. |
| UUID v4 вместо v7 | ⏳ требует миграционного решения | Изменение идентификаторов затрагивает модели/БД/совместимость. |
| README устарел | ✅ подтверждено | Manager import и product page уже существуют; дорожная карта требует обновления после завершения текущего пакета. |
| Production TLS | ⏳ runtime/deployment | Нельзя подтвердить статическим кодом без окружения. |
| Redis rate limiter | ✅ исправлено | slowapi использует общее Redis-хранилище счётчиков, URL собирается из `REDIS_HOST/PORT/DB`; покрыто конфигурационными тестами. |
| Dead code, schema drift | ⏳ отдельный аудит | Требуют отдельной ограниченной сверки; не смешивались с rate-limiter пакетом. |

## Пакет 2026-08-26 (2): публичная SEO-витрина (§16 п.29) + pre-deploy hardening (§16 п.30)

- Канон-first (§21): канон v1.8→v1.9 — новые п.29 (витрина без цен) и п.30 (куки Secure, CSP Report-Only, секреты, шифрование at rest, бэкапы как код); §6 дополнен блоком «Публичная витрина» (4 эндпоинта); SITEMAP — §3 (гость), §4 (дерево), §5 (два экрана `/brands`, `/brands/[slug]`).
- Витрина API: `api/v1/public.py` (brands, brands/{slug}, series/{slug}/products, photo?key=→307 presigned c валидацией префикса/суффикса) + `services/public_catalog.py` + `repositories/public_catalog.py` + `schemas/public_catalog.py`; кэш Redis тегом `catalog` TTL 300с (инвалидация импортом наследуется), rate-limit 60/min IP (`PUBLIC_RATE_LIMIT`). Slug серии — вычисляемый `_slugify` без колонки в БД (коллизии — первая по алфавиту; физический slug — отдельной миграцией при необходимости). Тесты `test_public_catalog.py` (~11): happy-path ×4, 404 ×4, отсутствие ценовых полей рекурсивно, 307 фото.
- Витрина frontend: `pages/brands/index.vue`, `pages/brands/[slug].vue` (SSR useAsyncData, useSeoMeta+OG, хлебные крошки, thumb через `/api/v1/public/photo`, CTA→/login, page_size=200 для длинных серий, 404 fatal для краулеров); `utils/envelope.ts::unwrapData`; типы PublicBrand*; consent.global пропускает `/brands/**`; `public/robots.txt` (Allow /brands, Disallow приватных зон); `server/routes/sitemap.xml.ts` (статика+бренды, in-memory 24ч, fail-open); noindex в layouts client/manager/miniapp; OG на лендинге.
- Куки/CSP (п.30): `settings.cookie_secure` (env `COOKIE_SECURE`) — единый флаг во всех set/delete_cookie auth-кук; prod-compose `COOKIE_SECURE=true`; `Content-Security-Policy-Report-Only` из `CONTENT_SECURITY_POLICY` (дефолт self-политика, пусто = off); тесты secure-флага ×2.
- Deps (pip-audit-driven): fastapi 0.115.0→**0.141.1** (starlette 0.38.6→**1.6.0** — закрыты PYSEC-2026-161/248/249/194x/228x), python-multipart→**0.0.32**, Pillow→**12.3.0**, Jinja2→**3.1.6**, weasyprint 62.3→**69.0** (+pydyf 0.12.1 вместо пина 0.11), slowapi→0.1.10; **python-jose→PyJWT[crypto]==2.13.0** (ушли транзитивные ecdsa/pyasn1 с advisory; `JWTError`→`jwt.PyJWTError` в security/deps/limiter/auth + 2 тестовых файла); dev: black→26.5.1, pytest→**9.1.1** (+pytest-asyncio 1.4.0, pytest-cov 7.1.0), **schemathesis удалён** (не использовался, ограничивал pytest/starlette сверху); Dockerfile: `pip install --upgrade pip` в base-stage (advisory самого pip).
- Метрики: **prometheus-fastapi-instrumentator удалён** — его routing несовместим со starlette 0.5x+ (`_IncludedRouter` без `.path` → AttributeError и 500 на КАЖДЫЙ запрос; не лечится даже версией 8.1.0). Замена — собственный `core/http_metrics.py`: ASGI-middleware + Histogram `http_request_duration_seconds{handler,method,status}` (resolve_handler c getattr-guard, 'unmatched' для 404) + явный `GET /metrics` (generate_latest). Имена метрик/лейблов сохранены — alerts.yml и дашборды Grafana совместимы.
- bandit: B701 (autoescape=False) в `core/templates.py` — `# nosec` с обоснованием (уведомления — plain text в JSON/SSE/Telegram, не HTML; PDF-окружение остаётся с autoescape=True).
- Бэкапы как код (п.30): `infra/scripts/restore_db.sh` (restore свежего/заданного дампа во временную БД `<DB>_restore_test` + проверка ключевых таблиц + cleanup-trap) + `make restore-test`; systemd юниты `infra/systemd/pp-backup.{service,timer}` (03:15) и `pp-restore-test.{service,timer}` (1-го числа 04:00); RUNBOOK: cron-строка заменена на systemctl enable таймеров, шаг .env дополнен (openssl rand, chmod 600, GF_SECURITY_ADMIN_PASSWORD≠admin, COOKIE_SECURE, требование шифрованного диска VPS).
- Healthchecks (п.30): api/web/nginx в dev-compose (наследуются prod-оверлеем): api — urllib на /healthz; web — node-fetch :3000 (start_period 90s под npm install); nginx — wget --spider /healthz end-to-end через прокси.
- Проверки: `make test` — **390 passed** (exit 0, pytest 9.1.1); ruff/eslint — чисто; **bandit -ll: 0 находок; pip-audit всего окружения: 0 уязвимостей** (включая transitives). Живые проверки через nginx :8081: `/healthz` 200; `/metrics` отдаёт histogram (40 серий); burst 65×`GET /api/v1/public/brands` → 429 (rate-limit работает); бренды отдаются без ценовых полей; `/brands` 200; `/sitemap.xml` содержит статика+бренды; CSP-Report-Only и nosniff на API-ответах.
- Остатки: живой прогон CI — при появлении раннера; перевод CSP в enforcing — после анализа отчётов на проде; физический slug серий — миграция при необходимости; полный переход access-куки на httpOnly/BFF — пост-MVP (ломает m-app).

## Пакет 2026-08-26: security-hardening (backfill §16 п.28) + CVE-deps + техдолг слоёв

> Backfill: hardening-пакет был применён в коде 2026-08-25 вечером, но не имел записи в каноне/журнале. Формализован как §16 п.28 (канон v1.7→v1.8). Этот пакет также закрывает часть накопленного техдолга из внешнего аудита.

- Канон-first (§21): §16 п.28 — (1) lockout брутфорса логина (Redis, `LOGIN_MAX_ATTEMPTS`/`LOGIN_LOCKOUT_MINUTES`, проверка до rate-limiter); (2) кэш живости сессии Redis TTL 60 с + немедленная инвалидация при отзыве (`services/cache.py`); (3) экранирование LIKE-метасимволов поиска (`_like_escape`, repositories/catalog.py); (4) `/healthz`//`readyz` без раскрытия env; (5) whitelist полей PATCH /auth/me (mass-assignment guard); (6) app-hardening main.py: Swagger/OpenAPI off в prod, CORS allowlist без `*`, security-headers, лимит JSON-тела 1 МБ, X-Request-ID + structlog context.
- Deps/CVE: `python-multipart==0.0.20` (CVE-2024-53981) и `python-jose[cryptography]==3.4.0` (CVE-2024-33663/33664); образ api пересобран, версии в контейнере подтверждены `pip list`.
- Слои (§4): прямой ORM `select(User)` из `api/miniapp.py` → `repositories/users.get_by_telegram_id` (поведение идентично); доменная логика diff/digest переехала из `repositories/price_changes.py` (320→~130 строк, только запросы) в новый `services/price_changes.py` (DTO + `compute_version_diff` + `find_digest_recipients`); обновлены импорты в `tasks/notifications.py`, `services/notifications.py`, `tests/test_price_changes.py`.
- Дедупликация Celery: новый `tasks/_common.py` — `create_worker_db()` (NullPool engine+sessionmaker) и `mark_redis_job_failed(service_module, job_id, message)`; `export_catalog`/`photo_zip`/`export_order_pdf` — тонкие обёртки (поведение прежнее, паттерн тестов `monkeypatch(_worker_session)` сохранён), `import_price_list` — только фабрика движка (его `_mark_failed` пишет статус версии в БД и остаётся собственной). Boilerplate в `notifications.py`/`fetch_nbrb_rates.py` сознательно не тронут — отдельным пакетом.
- Инфра/доки: Grafana-креды obs-overlay → `${GF_SECURITY_ADMIN_USER:-admin}`/`${GF_SECURITY_ADMIN_PASSWORD:-admin}` (+ vars в .env.example; admin/admin — dev-only); ссылки README/SITEMAP на канон v1.1 → v1.8; lint-фикс E702 в `tests/test_cache.py` (семантика фейкового Redis без изменений).
- Проверки: `make test` — **373 passed** (exit 0); `ruff check .` — чисто; eslint не гонялся (фронт не менялся).
- Остаток техдолга (не в этом пакете): компонентизация фронта (3 компонента на 35 страниц), vitest/i18n, UUIDv4→v7, N+1 профилирование, сверка каталога с §6 endpoint-by-endpoint, healthcheck'и api/web/nginx в compose.

## Пакет 2026-08-25 (1): SSE-стрим уведомлений (§16 п.26, снятие отложения п.20)

- Канон-first (§21): §16 п.26 — supersedes «SSE отложен» из п.20 (pull остаётся fallback); §6 `/notifications/stream` переписан: cookie-auth (query-токен исключён — логи), событие `notification`, heartbeat 20 с.
- Backend: `services/notification_events.py` — Redis pub/sub `notif:user:{id}`/`notif:broadcast`, sync-publish fail-open из 4 точек создания уведомлений (PRICE_CHANGED broadcast, PRICE_CHANGED_DIGEST, RATE_FETCH_FAILED broadcast, ACCOUNT_CREATED персональный); `GET /notifications/stream` (StreamingResponse, retry:5000, heartbeat `: ping`, подписка свой канал + broadcast при MANAGER, cleanup pubsub в finally); nginx (dev+prod): `location ^~ /api/v1/notifications/stream` с `proxy_buffering off; proxy_read_timeout 3600s`.
- Frontend: `useNotifications.startStream()` — единственный EventSource (same-origin, куки сами), `addEventListener('notification')` → `unreadCount++`; onerror CLOSED → close + fallback на существующий poll (оба — идемпотентные синглтоны, интервалы не дублируются); после reconnect — refresh() для ресинка; AppHeader: stream в onMounted, stopStream в onUnmounted (логаут/смена лейаута закрывают коннект).
- Тесты: +4 `test_notifications_sse.py` (401; publish→data-JSON сверка; heartbeat; broadcast только менеджеру); из-за буферизации httpx-ASGITransport написан локальный `_StreamingASGITransport` (только в тестах). `make test` — 363 passed; ruff/eslint/typecheck чисто.
- Живая проверка (:8081): клиентский стрим — retry + heartbeat + персональное событие (publish в user-канал) в тексте ответа; broadcast дошёл менеджерскому стриму, клиентский за то же окно получил только ping.
- Инфра-заметка: dev-порты параметризованы env (`DEV_DB_PORT/DEV_REDIS_PORT/DEV_NGINX_PORT`, дефолты 5432/6379/8080) из-за соседнего проекта на машине, конфликтующего портами; локально стек на 8081/5433/6380 (.env, не в git).

## Пакет 2026-08-21 (2): PDF-экспорт — каталог + заявка (фича F, §16 п.25)

- Канон-first (§21): §16 п.25 — закрытие отложенного п.16 (pdf-422) и фичи §16.1 F; дополнены §6 (catalog export pdf + POST /orders/{id}/pdf + GET /orders/export/{job_id}) и SITEMAP (job-паттерн вместо синхронного GET /orders/{id}/pdf).
- Deps: `weasyprint==62.3` раскомментирован + пин `pydyf==0.11.0` (0.12.1 ломает weasyprint 62.3 — `transform`→`set_matrix`); системные apt `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core` в Dockerfile base+runtime (после purge build-essential, не удаляются); образы api/worker/beat/bot пересобраны.
- Каталог: 422-заглушка снята; `_to_pdf_bytes` (Jinja2 `templates/pdf/catalog.j2`, autoescape-env `get_pdf_env()`), S3 `export/{job_id}.pdf` (application/pdf); лимит 10/час вынесен в `core/limiter.py` (общий с заявками).
- Заявка (F): таск `export_order_pdf` (паттерн export_catalog, S3 `export/order-{order_id}-{job_id}.pdf`), `start_order_pdf` в сервисе, `POST /orders/{id}/pdf` (клиент-владелец или MANAGER, 202 {job_id}, rate-limit 10/час) + `GET /orders/export/{job_id}` (владелец job, presigned при DONE); шаблон `order.j2`: реквизиты клиента (company/full_name/phone/email), позиции из product_snapshot с замороженными ценами, итог, курс (rate_source+exchange_rate).
- Frontend: пункт PDF в меню «Экспорт» каталога; композабл `usePdfExport.ts` (job-поллинг 2с×60, window.open presigned); кнопки «Скачать PDF» на `/orders/[id]` и per-row в `/orders` (busy-состояния, инлайн-ошибки); `ExportFormat += 'pdf'`.
- Проверки: `make test` — 359 passed (+12: pdf-202/magic вместо 422; order-pdf happy/404×2/MANAGER/StorageError→FAILED/статус+presigned); ruff/eslint/typecheck чисто; живая проверка через nginx: каталог-pdf job→DONE 0.65с → presigned 20 797 Б `%PDF-1.7` (кириллица в ToUnicode ок); заявка-pdf job→DONE 0.18с → 14 023 Б `%PDF-1.7`; autoescape проверен (`<script>` в company экранируется).
- Известные остатки: SSE-уведомления (отложено сознательно, п.20); УНП/адрес клиента в PDF-реквизитах появятся с расширением модели User.

## Пакет 2026-08-21 (1): prod-деплой-комплект + 1С-заглушки (Этап 11 + 11.5, §16 п.24)

- Канон-first (§21): §16 п.24 — рамка Этапа 11+11.5; §14 «Бэкапы» помечен (MVP: pg_dump -Fc + retention 30 д., WAL-G/MinIO-replication — пост-MVP).
- 1С (Этап 11.5, §18): subroute `/api/integrations/1c` отдельным include на app (вне /api/v1); 4 эндпоинта-заглушки §18.2 → 501 `{detail, schema_version}`; auth-dep `verify_integration`: пустой токен → 503, неверный `X-Integration-Token` (compare_digest) → 401, IP вне allowlist (CIDR, fail-closed при неизвестном IP) → 403; structlog-попытки; DTO `app/schemas/commerceml/` (заказы/прайс/склад/статусы CommerceML 2.x JSON, sku|guid-валидатор). Миграций нет (`external_id`/`external_1c_guid` уже были).
- TLS/nginx: self-contained `infra/nginx/nginx.prod.conf` (:80→301 + acme-challenge, :443 TLS1.3-only, HSTS, /metrics allow приватные сети, /healthz//readyz открыты); серты `infra/nginx/certs/` (gitignored), `make gen-self-signed-certs` (без перезаписи). `nginx -t` для dev и prod конфигов — успешен (nginx:1.27-alpine).
- Prod-харднинг: `docker-compose.prod.yml` — db/redis/minio `ports: !reset []`; найдены и исправлены 3 merge-бага оверлея (`volumes: []` не сбрасывала dev-маунты → `!override []`; web 3000 и nginx 8080 протекали из dev); `compose config` валиден — наружу только 80/443.
- Бэкапы: `infra/scripts/backup_db.sh` + `make backup`/`backup-list` — pg_dump -Fc в `infra/backups/` (gitignored), retention 30 д. (проверено живьём: дамп 62 КБ, pg_restore --list ок, старый файл удалён); restore + restore-test — в RUNBOOK (§11).
- Makefile: `prod-up/prod-down/prod-logs/prod-migrate` (DC_PROD + --env-file), gen-self-signed-certs, backup, backup-list.
- RUNBOOK `docs/RUNBOOK.md`: РБ-VPS (activeby/datacenter.by, §19), первый деплой, обновление/rollback (reversible-миграции), бэкапы (cron 03:15, pg_restore, restore-test 1/мес), TLS (self-signed/certbot), мониторинг (obs-up, алёрты §12 → действия), инциденты.
- CI `.github/workflows/ci.yml`: lint (ruff+eslint) → api-tests (services postgres/redis, TEST_DB_URL как в make test) → security (bandit+pip-audit) → build (docker build api/web, без push). Раннер недоступен — YAML валидирован, живой прогон при появлении репо на GitHub.
- Проверки: +27 `test_integrations_1c.py` (501/503/401/403, ip_allowed CIDR/IPv6/пустой/битый, 422 DTO, smoke /api/v1) — все зелёные, ruff чисто; полный suite — 347 passed (exit 0).

## Пакет 2026-08-20 (4): observability + тесты (Этап 10, §16 п.23)

- Канон-first (§21): §16 п.23 — рамка Этапа 10; в §12 перенос Loki/Tempo/Uptime Kuma помечен «Этап 11». Вошло: /metrics+Pushgateway+overlay-стек, Playwright-сценарии §13, k6-скрипты.
- API: `prometheus-fastapi-instrumentator` (http_request_duration_seconds по handler/status, `/metrics`, include_in_schema=False); nginx проксирует `/metrics` (в prod ограничить — Этап 11).
- Celery: `core/metrics.py` — Pushgateway-паттерн (fail-open, settings `pushgateway_url=""` = off): worker пушит `celery_task_duration_seconds`/`celery_task_failures_total` (task_postrun/prerun-сигналы, grouping instance=host:pid), beat каждые 30 с — `celery_queue_depth` (LLEN Redis).
- Инфра: `infra/docker-compose.observability.yml` + `infra/observability/` (prometheus.yml, alerts.yml — 4 правила §12: HighErrorRate>1%/5м, CeleryQueueBacklog>100, ImportFailed, InstanceDown; alertmanager.yml; Grafana provisioning: datasource + дашборды «PricePortal — API» и «PricePortal — Celery и импорты»). Makefile: `obs-up`/`obs-down` (Grafana :3001 admin/admin).
- E2E: `apps/web/e2e/` — auth-setup (storageState на роль, экономит лимит логина 5/15мин), 5 спеков §13 (логин ok/fail, поиск+фильтр каталога, корзина→checkout→заявка, экспорт CSV до DONE, импорт CSV с версией); `make test-e2e` (chromium в контейнере web, E2E_BASE_URL=IP nginx). Попутно фиксы: pre-existing eslint-ошибка в checkout.vue (неиспользуемая перем.), trace-режим конфига.
- k6: `infra/k6/catalog.js` (100 RPS/30с, thresholds p95<800ms, err<5%), `import_50k.js` + `gen_csv.py` (50k строк), README; `make test-load` / `make test-load-import` (k6 на хосте, опционально по §16 п.23).
- Проверки: `make test` — 320 passed (+6 test_metrics.py: /metrics, queue depth fakeredis, fail-open push), ruff/eslint/typecheck чисто; obs-up live: Prometheus targets 3×up, Grafana оба дашборда, alertmanager ready, метрики celery реально текут (beat push каждые 30с); `make test-e2e` — 9/9 passed (2.3м).

## Пакет 2026-08-20 (3): 2FA + журнал сессий (Этап 9, §16 п.22)

- Канон-first (§21): §16 п.22 — детализация контрактов фич H (2FA TOTP, MANAGER-only) и I (сессии, обе роли); дополнены §6 (7 новых эндпоинтов auth) и SITEMAP (`/profile/security`, `/profile/sessions`). `users.totp_secret` и `sessions` уже были в §5/моделях.
- Backend: deps `pyotp`+`qrcode`; миграция `a2e55697cb9c` — таблица `totp_recovery_codes` (хэши кодов, `used_at`); `create_2fa_ticket` (JWT type=2fa, TTL 5 мин, не пересекается с access по claim type); эндпоинты `POST /auth/2fa/setup|enable|verify|disable`, `GET /auth/sessions`, `DELETE /auth/sessions[/{id}]`; login-ветка `two_fa_required+ticket` без кук/сессии; verify — CSRF-exempt (§16 п.21) + rate-limit 5/15 мин (`rate_limit_2fa_verify`); recovery-одноразовость через `used_at`; аудит `user.2fa.enable/disable`; `GET /auth/me` + `totp_enabled`.
- Frontend: `pages/profile/security.vue` (wizard QR→код→recovery-коды 1 раз, отключение по коду/паролю), `pages/profile/sessions.vue` (таблица, бейдж «Текущая», «Завершить»/«Завершить все остальные»), двухшаговый `/login` (поле кода при `two_fa_required`), карточка «Безопасность» в профиле, типы в `types/api.ts`.
- Проверки: `make test` — 314 passed (+24 `test_auth_2fa.py`: полный флоу, recovery single-use, ticket-изоляция, rate-limit, 403 CLIENT, сессии CRUD, CSRF-exempt verify), ruff/eslint/typecheck чисто; живой e2e через nginx: login→ticket→verify→куки, setup/enable/disable, sessions delete — ок, тестовая 2FA после проверки отключена.

## Пакет 2026-08-20 (2): hardening-остатки MVP — CSRF стейл-куки, pp-bot, /privacy (§16 п.21)

- Канон-first (§21): §16 п.21 — `POST /auth/login` освобождён от CSRF-валидации (login-CSRF вне double-submit: запрос неаутентифицирован, креды передаются явно в теле); при 401 логин чистит остаточные куки `access_token`/`refresh_token`/`csrf_token`; §11 (CSRF) дополнен исключением login. Refresh/logout CSRF-проверку сохраняют.
- Backend: `core/deps.py` — exact-path exemption `/api/v1/auth/login` в `validate_csrf`; `api/v1/auth.py` — хелпер `_clear_auth_cookies` (переиспользован в logout и в ветке 401 логина; 401 отдаётся JSONResponse, т.к. куки с injected-Response теряются при raise HTTPException); `app/bot/__main__.py` — точка входа для `python -m app.bot` (pp-bot больше не рестарт-циклится).
- Frontend: `pages/privacy.vue` — публичная страница политики ПДн (Закон РБ № 99-З), layout default, без API; footer-ссылка имелась.
- Проверки: `make test` — 290 passed (+3 в `test_auth.py`: стейл-куки без CSRF → login 200; неверный пароль → 401 + чистка кук; refresh/logout всё ещё требуют CSRF), ruff чисто, eslint `privacy.vue` — 0 ошибок, SSR-рендер `/privacy` через nginx — 200.
- Закрывает известные остатки пакета 2026-08-17 (3): 403 при перелогине со стейл-куками; рестарт-цикл `pp-bot`.

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
