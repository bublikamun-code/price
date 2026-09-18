# 📋 Отчёт полного аудита — 2026-09-18

Контекст: аудит проведён после переноса дизайн-системы с прототипа CMR
shell-v2 (индиго `#4f46e5`, тёплый серо-бежевый фон, Manrope, плоские
карточки) поверх незакоммиченного UX-пакета (GlobalSearch, сортировки
таблиц, лендинг-блоки). Проверено: бэкенд-тесты, линтеры/типы, инфра-эндпоинты,
API-смоук + RBAC (агент), GUI-обход всех кабинетов (браузер).

## Среда

- Стенд: docker (pp-*), nginx :8081, образ web пересобран после правок стиля.
- Тестовые аккаунты: CLIENT `glass-test@svetvdome.by`, MANAGER `manager@example.by`,
  ADMIN `admin-test@svetvdome.by` (пароль сброшен аудитом на `AdminAudit2026`).

## ✅ Бэкенд

- `make test` — **395 passed** (exit 0; точечный вывод: 5×72+35, падений нет).
- `ruff` (api): **1 находка** — `app/main.py:192 E402` (импорт miniapp не в
 верху файла; саброут `/api/m/v1` регистрируется после основных — осознанно,
 но исключение не настроено в конфиге ruff). `eslint` + `vue-tsc` (web) —
  **0 ошибок** (исправлены в ходе подготовки: 8 eslint + 7 typecheck из
  незавершённого UX-пакета — см. «Правки»).
- `/healthz` → ok, `/readyz` → 200, SSE `/notifications/stream` → retry+ping,
  `/sitemap.xml` и `/robots.txt` → 200, публичный PDF каталога → 200 (6.6 МБ).
- Security-заголовки на API: `X-Request-ID`, `X-Content-Type-Options: nosniff`,
  CSP (см. замечание №2). Swagger `/api/docs` → 404 (доки на `/docs`).
- Rate-limit логина реально работает: во время аудита поймали живьём
  `429 Rate limit exceeded: 5 per 15 minute` по IP после серии логинов
  (счётчик `LIMITS:LIMITER/<ip>/auth/login/5/15/minute` в Redis).

## 🐞 Найденные проблемы

### №1 (P1) — Prometheus-метрики молча отключены: `/metrics` → 501
`app/core/http_metrics.py` **отсутствует в репозитории** (нет ни в одном
коммите). `main.py` импортирует его через try/except и при неудаче выставляет
`PrometheusMiddleware = None` → `/metrics` отвечает «Metrics not available»
(501). IMPLEMENTATION_STATUS (пакет 2026-08-26(2)) описывает этот файл как
реализованный и проверенный живьём (40 серий histogram) — но в git он не попал
(вероятно, правки выполнялись вне контроля версий и потерялись). Grafana-дашборды
и alerts.yml из observability-стека сейчас без данных. Требуется восстановить
`core/http_metrics.py` (ASGI-middleware + `generate_latest`).

### №2 (P2) — CSP включена в enforcing, канон описывал Report-Only
Ответ API несёт заголовок `content-security-policy: default-src 'self'; …`
(именно enforcing, не `-report-only`). Канон §16 п.30 фиксировал старт в
Report-Only с переводом в enforcing «после анализа отчётов». Либо канон
устарел, либо флаг перевернули — нужно сверить и зафиксировать решение в §16.

### №3 (P3) — 403 рендерится как «Что-то пошло не так»
`error.vue` различает только 404; для 403 (менеджер открывает `/manager/admin`)
пользователь видит код «403» и общий текст «Что-то пошло не так. Мы уже
разбираемся» — вместо понятного «Недостаточно прав». Код при этом отображается.

### №4 (P3) — admin-пароль из прошлого аудита не восстановлен
`admin-test@svetvdome.by` в начале аудита был с лок-аутом IP-лимитера (не
блокировкой аккаунта): агент смоука вошёл под `AdminAudit12345`. Для GUI-части
пароль сброшен напрямую в БД (bcrypt) на **`AdminAudit2026`** — это актуальные
креды. Стоит зафиксировать их в закрытом месте команды.

### №5 (P2) — presigned-ссылки не работают снаружи контейнеров (dev)
`GET /catalog/export/{job}` отдаёт job DONE + presigned URL на
`http://localhost:9000/...`, но скачивание → **403 SignatureDoesNotMatch**.
Причина: SigV4-подпись считается на внутреннем endpoint (`minio:9000`, Host
входит в подпись), затем хост строково заменяется на `localhost:9000`
(`storage.presigned_get`). Схема рассчитана на prod-nginx, который проксирует
MinIO с сохранением внутреннего Host — но в dev-конфе nginx **нет**
проксирования MinIO, и браузер бьёт напрямую в MinIO с чужим Host. Затронуто:
экспорт CSV/XLSX/PDF, фото, логи ошибок импорта — всё, что отдаётся
presigned. Фикс на выбор: в dev подписывать внешним endpoint (совпадает с
реальным Host) или добавить в dev-nginx location с `proxy_set_header Host`.

### №6 (P2) — web-корень (Nuxt через nginx) без security-заголовков
Заголовки `X-Content-Type-Options`, `X-Request-ID`, CSP, `Referrer-Policy`
есть только на ответах API (`/api/**`, `/docs`, `/healthz`, `/metrics`);
статика/SSR Nuxt (`/`, `/login`, …) отдаются без них. Добавить набор в
server-блок nginx (дёшево и закрывает единый вход §14).

## ✅ GUI-обход (браузер, обе темы)

- **Гость:** лендинг (новый стиль: бежевый фон/белые карточки/индиго CTA —
  скриншоты `gui-audit-screens/style-cmr-2026-09-17/`), `/brands`,
  `/brands/keaz` (полная номенклатура OptiBox Pro — регресс БАГ#6 из
  2026-09-10 отсутствует), `/privacy`, `/catalog` → редирект
  `/login?redirect=/catalog`. Логин с неверным паролем → «Неверный email или
  пароль». Лид-форма: валидация работает (кнопка disabled до заполнения);
  GUI-сабмит в этой сессии проверить инструментарием не удалось (ввод
  IAB-вкладки деградировал после серии операций) — HTTP-часть покрыта смоуком.
- **Клиент:** каталог (цены со скидкой −5%, фильтры, 12/147 по бренду,
  пагинация 13 стр.), корзина (2 позиции, итог 2 145,15 BYN = 698,85 +
  723,15×2 ✓, индиго CTA «Оформить заявку»), `/orders`, `/favorites`,
  `/notifications` (фильтры, read-all), `/profile` («Мои условия», валюта,
  сессии, Telegram), `/files`, `/bulk-add`, `/dashboard` — все H1 и данные
  на месте, текстов об ошибках нет.
- **Менеджер:** дашборд, заявки (новое: поиск, счётчики статусов, сортировка
  колонок, окно-пагинация), клиенты (матрица скидок −10/−15/−7, сортировка),
  каталог, импорт, файлы, новости, аудит, аналитика, бренды, баннеры, курсы
  валют — 12/12 страниц открываются корректно.
- **Админ:** `/manager/admin` — «Администрирование»: список пользователей с
  ролями, блокировка/сброс пароля, «Создать менеджера». RBAC подтверждён:
  менеджер на `/manager/admin` получает 403 (middleware role).
- Стиль CMR: светлая и тёмная темы проверены скриншотами (каталог, лендинг,
  корзина, заявки, клиенты, админ). Инверсии dark (btn-primary/nav-active/
  badge-primary → индиго) работают, контраст читаемый.

## 🔧 Правки, внесённые в ходе аудита (frontend, не закоммичено)

- `pages/index.vue`: удалён мёртвый код (advantages, BRAND_BLURBS, brandBlurb,
  pluralRu), ManagerContactModal перенесён внутрь корневого div (один корень
  шаблона).
- `pages/login.vue`: ManagerContactModal внутрь корневого div.
- `components/GlobalSearch.vue`, `pages/notifications.vue`: убраны `.value` у
  развёрнутых Pinia-флагов (`auth.isManager` и т.п.), типизация `any` →
  конкретные типы.
- `pages/profile/index.vue`: `catch (e: any)` → `getErrorMessage(e, …, { withMessage: true })`.
- `plugins/api.ts`: `onRequest` теперь async + `await nuxtApp.runWithContext(...)` —
  при потере контекста `runWithContext` возвращает Promise, и без await CSRF-
  заголовок мог тихо не ставиться (тип `string | Promise<string|null>` ловил vue-tsc).

## ⏳ Ограничения итерации

- Интерактивные клики в браузерной сессии деградировали после N операций
  (IAB-окружение): мутации через GUI (оформление заявки, смена статуса,
  создание сущностей) проверены API-смоуком, отображение — DOM/скринами.
- e2e Playwright (`make test-e2e`) не запускался (требует web-dev контейнер).

## API-смоук + RBAC (агент, ~213 проверок)

- **GET-смоук:** 31 эндпоинт × 4 роли (guest/client/manager/admin); финальный
  прогон 93 проверки — **0 отклонений**.
- **RBAC-негативы:** 16/16 (client→manager/admin 403 «Недостаточно прав»,
  guest→приватные 401, POST без X-CSRF-Token 403).
- **Позитивные мутации:** 13 (cart add/put/delete, order create 201, manager
  PATCH статуса, xlsx-export 200, price-version detail 200). FSM заявки
  подтверждена: `IN_PROGRESS → NEW` корректно отклоняется 409.
- **Валидация:** невалидный UUID → 422, несуществующий SKU → 404, пустое тело
  → 422, qty=0 → 422, bogus-статус → 422 — чисто.
- **Сессии:** SSE-стрим 200 (ping), refresh 200 (с другим User-Agent → 401 —
  анти-кража по UA работает), logout 204 → /auth/me 401. Куки
  access/refresh HttpOnly+SameSite=Lax, csrf без HttpOnly (double-submit).
- **Логаут-лимитер:** 3×401 → 429 на несуществующем email (5/15 мин на IP),
  перечисления email нет.
- `/api/docs` → 404, доки живут на `/docs` (200) и `/openapi.json` (200).
- **Celery end-to-end (GUI-часть):** POST /catalog/export → job DONE за ~3 c,
  но скачивание по presigned-URL → 403 (см. находку №5).
- Не проверено агентом (нет данных/осознанно): `/news/{id}`, `/files/{id}/download`
  с реальными id (в БД нет сущностей), 2FA/forgot-password/telegram-link/CSV-импорт
  (персистентные мутации), account-lockout на реальном аккаунте.

## Приложение: скриншоты

- `gui-audit-screens/style-cmr-2026-09-17/` — стиль CMR (лендинг/каталог, 2 темы).
- `gui-audit-screens/audit-2026-09-18/` — корзина клиента, заявки/клиенты
  менеджера, админ-панель (тёмная тема), каталог в светлой.
