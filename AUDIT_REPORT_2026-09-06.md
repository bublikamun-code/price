# 🛠 Полный аудит проекта «Клиентский портал с прайс-листами» — 2026-09-06

Скоуп: бэкенд (безопасность, надёжность, архитектура), контракт API фронт↔бэк, фронтенд (код, юзабилити), инфраструктура, визуальная проверка ключевых страниц.
Методы: 5 направленных аудитов кода (в т.ч. с grep-срезами по всем роутерам/сервисам), curl-проверки живого стека, анализ логов, GUI-обход в браузере (скриншоты в `gui-audit-2026-09-06/`).

---

## 0. Резюме: топ-10 глобальных проблем

| # | Проблема | Уровень | Где |
|---|---|---|---|
| 1 | **Случайные разлогины**: гонка параллельных refresh-запросов — подтверждено логами (3×401 → 2 refresh-а с одним токеном → 401 → logout) | 🔴 P0 | `apps/web/composables/useApi.ts`, `apps/api/app/services/auth.py` |
| 2 | **Кластер 404 API**: `/api/v1/public/brands`, `/public/brands/{slug}`, `/public/series/{slug}/products`, `/public/photo` — раздел «Бренды» мёртв (страницы есть, данных нет) | 🔴 P0 | `apps/api/app/api/v1/public.py:7` vs `pages/brands/*.vue` |
| 3 | `/api/v1/admin/managers` → 404: страница `/manager/admin` полностью нерабочая | 🔴 P0 | `admin.py:7` vs `pages/manager/admin.vue` |
| 4 | `/api/v1/auth/change-password` → 404: первичная смена пароля (force-change-password) сломана | 🔴 P0 | `pages/force-change-password.vue:25`, `api/v1/auth.py` |
| 5 | `/api/m/v1/auth/telegram` → 404: вход в Telegram Mini App не работает (модуль `miniapp` не существует) | 🔴 P0 | `main.py:191-193`, `composables/useTelegram.ts:71` |
| 6 | **Страницы `/news` не существует** (есть только `news/[id].vue`) → 404 по ссылке из дашборда | 🔴 P0 | `apps/web/pages/news/` |
| 7 | **Rate-limit не работает за nginx**: uvicorn без `--proxy-headers` — все клиенты с одного IP; 5 неудачных входов кого угодно = 429 для всех (DoS) | 🔴 P0 | `apps/api/Dockerfile:70`, `core/limiter.py:14` |
| 8 | `/manager/analytics` доступна **гостю** (подтверждено: 200 без куки) — сломанный role-guard | 🔴 P0 | `middleware/role.ts:6-7`, `pages/manager/analytics.vue:2` |
| 9 | **pp-bot в crash-loop**: `No module named app.bot.__main__`, бесконечные перезапуски | 🟠 P1 | `infra/docker-compose.yml:155+` |
| 10 | Данные предыдущего пользователя остаются в UI после logout (корзина/избранное/уведомления — module-level state) | 🟠 P1 | `useFavorites.ts:11`, `useCart.ts:5-8`, `useNotifications.ts:7` |

Полный перечень — по разделам ниже. Итого: **~55 находок** (P0: 10, P1: ~20, P2: ~25).

---

## 1. Инфраструктура

### 🔴 P0/P1
- **[P1] pp-bot crash-loop.** `docker logs pp-bot`: `No module named app.bot.__main__; 'app.bot' is a package and cannot be directly executed` — рестарт каждые ~15 секунд месяцами. Бот — заглушка, но сервис жрёт ресурсы и портит monitoring. Фикс: убрать сервис из `docker-compose.yml` (или добавить `bot/__main__.py`).
- **[P1] Веб работает на Nuxt dev-сервере, не prod-сборка.** В интерфейсе видны Nuxt DevTools (пилюля «Page load time», кнопки Toggle DevTools/Component Inspector). Это медленно, раскрывает внутренности и ломает автоматизированные клики (см. §7). Фикс: prod-сборка (`npm run build` → `node .output/server/index.mjs`) в `Dockerfile` веба.
- **[P1] Два стека одновременно.** На машине живут `crm-svetvdome-frontend/backend` (порт 80, чужой проект) и `pp-*` (8081/8000/3000). Вероятная причина «рассинхрона на сервере» из аудита 04.09: не тот порт/не тот стек. Фикс: оставить один стек; entry-point — `http://localhost:8081` (nginx).
- **[P2] pp-nginx вечно «unhealthy».** Healthcheck `wget --spider http://localhost:80/healthz` проксируется в API (nginx.conf:72) — при рестарте API nginx «нездоров», плюс busybox-wget нестабилен. Реально nginx работает (проверено: 200). Фикс: отдавать `/healthz` статикой из nginx (`return 200`), не проксировать.

### ✅ В порядке
pp-api/pp-web/pp-db/pp-redis/pp-minio healthy; pp-worker/pp-beat работают; CORS без `*`; куки httpOnly+SameSite=Lax (+Secure в prod-компоузе).

---

## 2. Безопасность бэкенда

Сильные стороны (проверено, в порядке): bcrypt cost 12; JWT — алгоритм зафиксирован при decode, prod RS256 из PEM, access 15 мин; refresh — opaque + SHA-256 в БД, ротация, привязка к User-Agent, отзыв сессий; IDOR-проверки на заказах/уведомлениях/корзине/избранном/файлах/export-jobs; security-заголовки; SQL параметризован; сортировка через whitelist; загрузки — расширение+mime+magic bytes+размер; Swagger выключен в prod.

### Находки
- **[HIGH] Rate-limit за nginx не работает** — `Dockerfile:70`, `core/limiter.py:14`, `api/v1/auth.py:67-68`: uvicorn без `--proxy-headers --forwarded-allow-ips`; `request.client.host` = IP nginx. Пер-IP лимиты (login 5/15min) становятся глобальными: 5 неудач любых пользователей → 429 всем; `sessions.ip` всегда пишет IP nginx (auth.py:467). Фикс: `--proxy-headers` + доверенный X-Forwarded-For.
- **[HIGH] CSRF-гейт обходим через куку `auth_token`** — `core/deps.py:33` vs `:62`: CSRF требуется только при cookie `access_token`/`refresh_token`, но аутентификация принимается и по не-httpOnly `auth_token` (ставит фронт). Запрос только с `auth_token` проходит POST/DELETE без CSRF. Фикс: учитывать `auth_token` в CSRF-условии (а лучше — уйти от JS-куки совсем, см. фронт §6).
- **[MEDIUM] Лок аккаунта по email = DoS аккаунтов** — `services/auth.py:118-134`: 5 неверных паролей лочат любого пользователя на 30 мин. Фикс: ключ email+IP, экспоненциальные задержки, уведомление владельцу.
- **[MEDIUM] `/metrics` наружу без auth** — `infra/nginx/nginx.conf:75-77`. Фикс: `allow <внутренняя сеть>; deny all;`.
- **[MEDIUM] Пароль из 1 символа разрешён** — `schemas/auth.py:21,227-230` (`min_length=1`) при set/reset. Критично в связке с P0-4: поток force-change-password как раз единственное место установки пароля. Фикс: `min_length=8`+.
- **[MEDIUM] Восстановление пароля не работает** — `services/email.py:45-47` no-op, а эндпоинт отвечает 202 «отправлено» (`api/v1/auth.py:321-341`). Пользователь никогда не получит письмо. Фикс: SMTP в `tasks/email.py` или честная 501.
- **[MEDIUM] Telegram-заглушки** — `telegram_auth.py:5-7`: `/auth/telegram/link-code` возвращает код `"STUB"`; HMAC-верификация initData не реализована. Фикс: 501 до реализации; при реализации — HMAC-SHA256 + проверка auth_date.
- **[LOW] `/auth/reset-password` без rate-limit** (auth.py:344-360); **дефолтные креды** `POSTGRES_PASSWORD: price_secret`, `MINIO_ROOT_PASSWORD: minioadmin` (docker-compose.yml:15,52-53); **temp-пароль без флага обязательной смены** (manager_users.py:66,192); **MaxBodySize только по Content-Length** — chunked проходит (main.py:144-155); **access-JWT без `sid` принимается** (deps.py:121-128) — ослабляет мгновенный отзыв.

---

## 3. Надёжность бэкенда

Сильные стороны: паттерн «сервис flush — роутер commit» выдержан, rollback-версий прайса через FOR UPDATE; pool_pre_ping + pool_size=10/overflow=20; Celery-задачи с отдельными движками (NullPool); пагинация с капами на всех списках; построчные ошибки CSV-импорта; курс НБ РБ с fallback-алёртом; structlog + X-Request-ID.

### Находки
- **[CRITICAL] Импорт прайса зависает навсегда в PROCESSING** — `tasks/import_price_list.py:246`: при смерти воркера (OOM/hard limit 30 мин) повторно доставленная задача уходит в «skipped» (:89-92), `_mark_failed` не вызывается — версия висит в PROCESSING вечно, без логов. Фикс: beat-reconciler «PROCESSING > N часов → FAILED» / stale-lock по `started_at`.
- **[HIGH] Гонка в `_lock_version`** — `import_price_list.py:239-249`: check `QUEUED→PROCESSING` без `SELECT … FOR UPDATE`; при `task_acks_late + reject_on_worker_lost` два воркера импортируют параллельно (дубль PriceHistory). Фикс: `with_for_update()` как в `rollback_version:113-117`.
- **[HIGH] N+1 в экспорте каталога** — `tasks/export_catalog.py:113-115`: `price_product` на каждую строку = 2 SQL/товар; на 50–100k SKU это 100–200k запросов → soft time limit 25 мин убьёт job. Фикс: resolve курса/скидок один раз перед циклом.
- **[HIGH] N+1 в корзине и заказе** — `services/cart.py:40`, `order.py:66-77`: ~3 запроса на позицию (50 позиций ≈ 150 запросов). Фикс: `get_by_skus` батчем, курс 1 раз.
- **[MEDIUM] Две корзины одному клиенту** — `models/order.py:21-23` + `repositories/cart.py:11-17`: `carts.user_id` без UNIQUE, get_or_create = check-then-insert. Фикс: UNIQUE + обработка IntegrityError.
- **[MEDIUM] Гонка `next_order_seq`** — `repositories/orders.py:16-23`: `MAX(seq)+1` → конкурентное создание заявок падает по `uq_orders_seq` 500-й. Фикс: PG sequence или ретрай.
- **[MEDIUM] Oversell остатков** — `services/order.py:73-74`: проверка `quantity > stock_qty` без блокировки строки. Фикс: `with_for_update()` на товар.
- **[MEDIUM] Дубли уведомлений о ценах** — `tasks/notifications.py:74-79`: dispatch не идемпотентен (re-delivery → дубли in-app). Фикс: ключ идемпотентности (SETNX/таблица).
- **[MEDIUM] Потеря уведомлений без ретрая** — `tasks/notifications.py:82-86`: `autoretry_for=()` гасит любые сбои в `{"status":"error"}`.
- **[MEDIUM] boto3 без таймаутов** — `services/storage.py:36-45`: подвисший MinIO блокирует импорт/выгрузку на дефолтные 60с×5 ретраев. Фикс: `connect/read_timeout=10-15s`, `max_attempts=2`.
- **[MEDIUM] `/readyz` проверяет только `SELECT 1`** — `api/v1/health.py:23-41`; Redis/MinIO не проверяются, хотя от них зависят кэш/SSE/импорт/экспорт.
- **[MEDIUM] Export-job «RUNNING» навсегда** — `services/export.py:12-16,79`: стейт только в Redis; смерть воркера = клиент поллит до TTL 24ч. Фикс: heartbeat/дедлайн в стейте.
- **[MEDIUM] Дрейф моделей→миграций реален** — `alembic/versions/0007_sync_models_drift.py` собрал 6 пропущенных объектов (password_reset_tokens, totp_recovery_codes, orders.seq и др.). Фикс: CI-шаг `alembic check`.
- **[LOW]** `archive_missing` с `NOT IN` на 100k SKU (import_price_list.py:226-227); FAILED-версию нельзя откатить если упал upload error-log (import_price_list.py:252-264); дубли sku в CSV — «последний wins» молча; `engine.dispose()` отсутствует в lifespan (main.py:42-48); в Celery-задачах нет request_id в логах.

---

## 4. Структура / архитектура бэкенда

- **Слои выдержаны хорошо.** Прямой доступ к БД в роутерах — только `health.py` (приемлемо). Роутеры тонкие: бизнес в сервисах, репозитории возвращают модели. Сервисы с raw `select()`: `auth.py`, `pricing.py`, `price_list_import.py` — точечно, не системно.
- **response_model покрытие ~90%** (110 эндпоинтов / 96 с типизированным ответом). Без типизации остались: favorites (2/3), files, notifications (2/4), manager/banners (3/5), brands (4/5), currencies (2/3), manager/files (2/3), news (3/4), products (3/4) — в основном 204-ответы, но стоит довести до 100%.
- **Дубли сервисов нет**: `dashboard.py` (менеджерский) vs `client_dashboard.py` (клиентский) — разные скоупы, оба используются.
- **Мёртвого кода в сервисах нет** (все 24 сервиса импортируются), но есть **заглушки, которые фронт вызывает** (public.py, admin.py — см. §5) и отсутствующий `api/miniapp.py` (условный импорт в main.py:191-193).
- **Тесты: ~29 файлов**, покрытие по слоям широкое (auth, cart, catalog, orders, favorites, files, notifications, export, импорты, все manager-контроллеры, JWT RS256, health). Заметный плюс проекта.
- **[MEDIUM] Условно подключаемый роутер** (`miniapp=None`) — паттерн «модуль может отсутствовать» скрыл поломку фичи 0006 (см. P0-5). Лучше fail-fast.

---

## 5. Контракт API фронт ↔ бэк

Проверено и СОШЛОСЬ (не трогать): формат `{data, meta}` на всех списках; ошибки `{detail}` ↔ `utils/errors.ts`; пагинация `page/per_page`; catalog по `sku`; news (0004), banners (0005), telegram link-code, cart, 2FA envelope, query-параметры списков.

### 🔴 Мисматчи (подтверждены curl-ом на живом стеке)
| Вызов фронта | Ответ сервера | Следствие |
|---|---|---|
| `GET /api/v1/public/brands` | **404** | Страница `/brands` — 200-оболочка с вечной ошибкой загрузки |
| `GET /api/v1/public/brands/{slug}` | **404** | Деталка бренда недоступна |
| `GET /api/v1/public/series/{slug}/products` (+`page_size` вместо `per_page`) | **404** | Товары серии недоступны |
| `GET /api/v1/public/photo?key=` | **404** | Битые картинки брендов |
| `GET/POST/PATCH /api/v1/admin/managers[/{id}]` | **404** | `/manager/admin` мёртвая целиком |
| `POST /api/v1/auth/change-password` | **404** | Поток первой смены пароля заблокирован |
| `POST /api/m/v1/auth/telegram` | **404** | Вход в Mini App не работает (роутер не существует) |

### Мёртвый API (фронт не зовёт)
`GET /public/`, `GET /admin/` (заглушки 501), `GET /manager/ping`, `GET /catalog/export/{job_id}/download`, `POST/DELETE /manager/products/{id}/photos` (фронт грузит фото только серий).

---

## 6. Фронтенд: код и юзабилити

Сильные стороны: strict TS, ноль `v-html`/`any`/`ts-ignore`, двойной submit защищён везде, empty states и error+retry почти везде, пагинация в manager-списках, safe-area в miniapp-layout, useHead на всех страницах, typeahead с защитой от гонок.

### Находки
- **[HIGH] Гонка refresh → logout** (переносится в UX): при 3+ параллельных запросах все получают 401, все шлют refresh одним токеном, двое получают 401 → `navigateTo('/login')`. Подтверждено логами pp-api (01:36: два `POST /auth/refresh` — один 200, один 401). Фикс: single-flight refresh (общий promise + очередь) в `useApi.ts`; на бэке — grace-окно для старого refresh-токена.
- **[HIGH] Дашборд главной вечно в скелетонах** — `pages/index.vue:156-163`: `onMounted → if (isAuthenticated && isClient) loadDashboard()` — если сессия восстанавливается после монтирования (после refresh/401), `loadDashboard()` не вызывается никогда; `ordersLoading` остаётся `true`. Подтверждено визуально + отсутствием запроса `/api/v1/orders` в логах. Фикс: `watch([isAuthenticated, isClient], …, { immediate: true })`.
- **[HIGH] `/manager/analytics` без защиты** — `analytics.vue:2` (`middleware: ['role']` без `auth`/`roles`; `role.ts:6-7` — no-op при пустом roles). Подтверждено: SSR 200 у гостя. Фикс: `['auth','role']` + roles.
- **[HIGH] Чужие данные в UI после logout** — module-level state `useFavorites`/`useCart`/`useNotifications` не сбрасывается в `useAuth.clear()` (useAuth.ts:140-149); `ensureLoaded()` при новом пользователе делает ранний return. Фикс: сброс в `clear()`/`login()`.
- **[HIGH] 401 в мини-аппе ведёт на веб-`/login`** — `useApi.ts:26`. Фикс: `route.path.startsWith('/m') ? '/m' : '/login'`.
- **[MEDIUM] Бейдж уведомлений мёртвый** — `useNotifications.startPolling/startStream` не вызываются нигде; кнопка-колокольчик в шапке без `@click` и `aria-label` (AppHeader.vue:104-112). SSE на бэке тоже заглушка (`notification_events.py:29-31`).
- **[MEDIUM] Отмена заявки менеджером без подтверждения** (необратимый переход FSM) — `manager/orders/[id].vue:65-82`; у клиента confirm есть.
- **[MEDIUM] Блокировка клиента без подтверждения** — `manager/users/[id].vue:113-135` (в `admin.vue` confirm есть).
- **[MEDIUM] Гонки `load()` в каталоге** — `catalog/index.vue:134-160`, `m/catalog/index.vue:36-77`: быстрая смена фильтров → поздний ответ перетирает свежие данные. Фикс: seq/AbortController (в typeahead уже есть).
- **[MEDIUM] Поллинг PDF без cleanup** — `usePdfExport.ts:62`: после ухода со страницы запросы продолжаются до MAX_POLLS.
- **[MEDIUM] Токен в JS-куке без `secure`** — `useAuth.ts:77-84` (`auth_token`/`auth_user` читаемы JS). В связке с CSRF-дырой (§2). Фикс: httpOnly-сессия с сервера.
- **[MEDIUM] `/m/orders` — `per_page: 50` без load-more** — заявки старше 50 недостижимы (m/orders/index.vue:23).
- **[LOW] Консистентность**: `STATUS_META`/`TYPE_META` скопированы в 10 файлов; три разных паттерна подтверждения (`window.confirm`, inline, модалка); в `manager/orders/[id].vue:180` суммы считаются на клиенте `toFixed(2)` (риск копеек) и без `formatMoney`; пагинационная навигация копипаста в ~8 местах; «Загрузка…» vs «Загрузка...»; сырой EN-статус в fallback шапки (AppHeader.vue:203); `pages/manager/admin.vue:144-149` — текстовые loading/empty вместо skeleton; EmptyState.vue используется только на /dashboard.
- **[LOW] A11y**: иконки пагинации без aria-label; кликабельные div уведомлений/строк таблиц без keyboard-доступа; `ConsentModal.vue:71` — `target="_blank"` без `rel="noopener"`.

---

## 7. Визуальный GUI-аудит (живой стек)

Что проверено в браузере (скриншоты в `gui-audit-2026-09-06/`):

| Страница | Результат | Замечания |
|---|---|---|
| `/` (дашборд клиента) | ⚠️ | Карточки «Последние заявки/Избранное/Файлы» **вечно в скелетонах** (P0-баг, см. §6). Компоновка карточек чистая, сайдбар-пилюля аккуратная |
| `/catalog` | ✅ | Фильтры/поиск/сортировка/экспорт/пагинация работают, бейдж «В корзине · N» на карточках. Пилюля пагинации слегка перекрывает нижний ряд карточек. Дубли названий — семпл-данные |
| `/catalog/382526` (карточка) | ✅/⚠️ | Характеристики, похожие товары серии, цена — ок. **Описания товара нет в DOM**; «Вес, г: **9016 г**» — единица и в лейбле и в значении; нерусские лейблы атрибутов («Din rail», «Transparent window») |
| `/login` | ✅ | Чистая форма, понятный копирайтинг, ошибка «Неверный email или пароль» показывается корректно. «Связаться с менеджером» — `href="#"` (заглушка) |
| `/brands`, `/manager/admin`, `/news` | 🔴 | Серверно подтверждено: раздел брендов и админ-страница зовут несуществующие API; `/news` — 404 |
| `/manager/*`, `/m/*` | — | Визуально не обойдены из-за нестабильности браузерной среды (клики и захват кадров в IAB рвались на dev-сервере); покрыты код-аудитом §6 + визуальным аудитом 04.09 (`gui-audit-screens/`, `UI_AUDIT_REPORT_2026-09-04.md`): мобильные каталог/корзина/заявки/профиль и менеджер-дашборд тогда прошли проверку |

Серверные проверки маршрутов (curl, живой стек): все клиентские защищённые страницы отдают SSR-302 на /login для гостя (корректно); **`/manager/analytics` — 200 гостю (баг)**; **`/news` — 404**; `/privacy`, `/reset-password`, `/login`, `/brands` — 200.

Тестовые данные, оставленные аудитом: пароль клиента `glass-test@svetvdome.by` сброшен на `AuditTest12345` (аккаунт создан аудитом 04.09).

---

## 8. План устранения (чтобы закрыть все глобальные ошибки)

### P0 — ломает пользователей сейчас (1–2 дня)
1. **Refresh single-flight** в `useApi.ts` (+ grace-окно старого refresh на бэке) — убирает случайные разлогины.
2. **`pages/index.vue`**: `watch(isAuthenticated, {immediate})` вместо голого `onMounted` — убирает вечные скелетоны главной.
3. **Реализовать или отключить**: public brands API (4 эндпоинта), admin managers, change-password, miniapp telegram. Минимум — скрыть пункты «Бренды», «Администрирование», телеграм-привязку и страницу force-change-password до готовности бэка.
4. **Создать `pages/news/index.vue`** (список) — сейчас 404.
5. **`--proxy-headers --forwarded-allow-ips`** в Dockerfile API + доверие X-Forwarded-For в nginx — чинит rate-limit и IP в сессиях.
6. **Guard на `/manager/analytics`**: `middleware: ['auth','role'], roles: ['MANAGER','ADMIN']` (+ поправить сам `role.ts`, чтобы пустой roles не был no-op).
7. **CSRF**: учитывать `auth_token` в deps.py (или перевести фронт на httpOnly-токены).
8. **pp-bot**: убрать из compose до реализации; **один стек** на машине (снять crm-svetvdome), prod-сборка web.

### P1 — надёжность и данные (~1 неделя)
9. Reconciler «PROCESSING > N ч → FAILED» + `FOR UPDATE` в `_lock_version`.
10. `UNIQUE (carts.user_id)` + миграция; seq заявок через PG sequence; `FOR UPDATE` на остатки при заказе.
11. Батч-цены в корзине/заказе; разовый resolve курса/скидок в экспорте.
12. boto3 таймауты; `/readyz` + Redis + S3; идемпотентность и ретраи dispatch уведомлений; heartbeat для export-jobs.
13. Email: SMTP-отправка или честная 501 (и починить «Забыли пароль?» end-to-end).
14. Сброс state composables при logout/login; redirect `/m` при 401 в мини-аппе.
15. CI: `alembic check` против моделей (защита от дрейфа 0007).

### P2 — полировка (по мере развития)
16. Confirm на отмену заявки и блокировку клиента; единый ConfirmDialog-компонент.
17. `STATUS_META`/`TYPE_META` → `utils/constants.ts`; `PaginationNav.vue`; `formatMoney` в менеджере (убрать клиентский `toFixed`).
18. Запустить polling/SSE уведомлений + рабочая кнопка-колокольчик (и SSE на бэке — сейчас заглушка).
19. A11y: aria-label на иконок-кнопках, keyboard-доступ к кликабельным карточкам, `rel="noopener"`.
20. Пагинация/load-more в `/m/orders`, `brands`, `banners`, `currency`.
21. Пароли `min_length=8`; `/metrics` закрыть интранетом; флаг `must_change_password` для temp-паролей; `engine.dispose()` в lifespan; request_id в Celery-логах.
22. Данные товара: описания в импорте, единицы не дублировать в значениях атрибутов, русифицировать лейблы атрибутов (словарь в импортере).

---

## 9. Методика и ограничения
- Код-аудиты: 4 профильных агента + ручные grep-срезы (роутеры/сервисы/схемы/тесты/мёртвый код).
- Живой стек: `http://localhost:8081` (nginx → pp-web:3000 dev + pp-api:8000); логи pp-api/pp-nginx/pp-web/pp-bot; прямые curl-проверки API и SSR-статусов.
- GUI: браузерный обход в IAB; из-за нестабильности клика/захвата на dev-сервере визуально проверены 4 ключевых страницы, остальные покрыты код-аудитом и визуальным аудитом от 04.09. Прод-сборка веба (P0-8) также улучшит тестируемость.
- Не проверялось: нагрузочное тестирование, аудит зависимостей (pip audit/npm audit) — рекомендую добавить в CI.
