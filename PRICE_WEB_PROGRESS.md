# Price Web — прогресс полной замены web и миграции API v2

> **Дата последнего обновления:** 2026-09-24  
> **Канон:** `ARCHITECTURE_PLAN.md` v2.0, `SITEMAP.md` v2.0 и документы в `docs/`.  
> **Основной проект:** `/Users/yaroslav/Documents/Price web`.

## Назначение

Этот файл — рабочий трекер полной замены frontend и целевых изменений backend для новой B2B-модели. Он не описывает ожидаемую работу как «редизайн поверх старых страниц» и не считает завершённым код, которого ещё нет.

Проект уже содержит работающую основу:

- `apps/web` — Nuxt 3, Vue 3, TypeScript, Tailwind, Pinia, SSR;
- `apps/api` — FastAPI, SQLAlchemy, Alembic, PostgreSQL;
- Redis, Celery, MinIO, Docker Compose, Nginx;
- authentication/RBAC, каталог, цены, корзину, заявки, импорт, файлы, уведомления и manager tools.

Статический прототип в `price-web-samples` остаётся **reference-only**. Он не переносится в runtime, не становится вторым frontend и не дублирует production API/store logic.

## Статусы

- `[x]` — завершено и подтверждено;
- `[~]` — выполняется;
- `[ ]` — ещё не начато;
- `[!]` — заблокировано входными данными или внешней инфраструктурой.

## Зафиксированные решения

- [x] Работаем только в существующем проекте; второй Nuxt/Next.js frontend не создаём.
- [x] Заменяем frontend presentation полностью, а не перекрашиваем существующие страницы.
- [x] Backend core не переписываем ради cosmetic redesign.
- [x] Backend меняется там, где этого требуют B2B organization model, web/iOS contract и корректная commerce-логика.
- [x] `/api/v1/**` остаётся совместимым во время миграции.
- [x] Новый frontend и будущий iOS используют канонический `/api/v2/**`.
- [x] Organization становится владельцем коммерческих условий; user остаётся login identity, contact и member.
- [x] Workflow — создание заявки, а не оплаченного заказа и не автоматическое резервирование остатка.
- [x] Доступность проверяется при создании компонентов, а не оформляется отдельным редизайном после разработки.
- [x] Визуальное направление — Trade: тёплый светлый canvas, тёмно-зелёные служебные поверхности, terracotta action, плотная прямоугольная сетка.
- [x] Light theme — основная; dark theme — полноценная вторая тема.
- [x] Manrope используется для интерфейса, IBM Plex Mono — для SKU, цен, остатков и технических данных.
- [x] Pill/capsule containers, floating glass cards, ambient orbs, gradient glow и старая rounded-card система не переносятся.
- [x] SwiftUI-разработка начинается после стабилизации web и API v2.

## Канонические документы

- [x] `ARCHITECTURE_PLAN.md` обновлён до v2.0: новая граница работ, organization schema, API v2 и Decisions Log 31–35.
- [x] `SITEMAP.md` обновлён как целевая карта: `/` всегда public landing, клиент начинает с `/dashboard`, manager — с `/manager`.
- [x] `docs/TRADE_DESIGN_SYSTEM.md` создан как визуальный и accessibility-контракт.
- [x] `docs/REPLACEMENT_FRONTEND_ARCHITECTURE.md` создан как контракт новой frontend domain architecture.
- [x] `docs/API_V2_CONTRACT.md` создан как рабочий v2 cross-client контракт; далее синхронизируется с OpenAPI.
- [x] `docs/IOS_API_CONTRACT.md` создан как projection для будущего SwiftUI-клиента.
- [x] Обновить исторический статус и traceability-ссылки без переписывания истории аудита.
- [x] Проверить документацию read-only `git diff --check`, `git diff --stat`, `git status --short` и targeted contradiction scan; статическая проверка текущего среза пройдена, неожиданных изменений рабочего дерева не обнаружено.

## Защита текущего рабочего дерева

До начала миграции дерево уже было существенно изменено. Эти изменения принадлежат текущему проекту и должны быть сохранены.

- [x] Зафиксирован baseline незакоммиченных файлов.
- [x] Запрещены `git reset --hard`, `git checkout -- .`, `git clean -fd` и массовое удаление untracked-файлов.
- [ ] Перед каждым этапом сверять изменяемые файлы с baseline.
- [ ] Не помечать чужие незакоммиченные изменения как результат текущего этапа.

---

# Этап 0. Baseline и канон

**Статус:** `[x]` — канон, baseline и read-only проверка документации завершены; рабочее дерево сохранено.

- [x] Определены сохраняемые backend capabilities: refresh rotation, CSRF, sessions, 2FA, consent, RBAC, pricing formulas/rates, frozen order prices, FSM, audit, imports, rollback, jobs, storage validation.
- [x] Определены targeted backend changes: organization model, v2 contracts, money/errors, structured delivery, UUID writes, media resources, idempotency, concurrency, server-side search/sort/cursor.
- [x] Зафиксирована граница presentation/domain/backend.
- [x] Зафиксирована последовательность миграции и rollout по vertical slices.
- [x] Завершить read-only проверку документации.
- [x] Зафиксировать migration fixture со старой схемой и детерминированными legacy-данными.

**Gate:** канон не противоречит друг другу; runtime implementation ещё не начата; новые документы не перезаписывают пользовательские изменения.

# Этап 1. Критические backend-контракты

**Статус:** `[~]` — v1 order-create compatibility и v2 transport с session/current-user, organization-aware catalog, order collection/detail/actions и полным client cart contract реализованы; native auth, media, notifications/jobs и manager surfaces ещё не завершены.

## Money и formats

- [~] Ввести единое публичное v2-представление `{amount: decimal-string, currency: ISO-4217}`.
- [x] Не смешивать JSON float и Decimal в реализованных v2 order, catalog и cart projections; полный dashboard/files/jobs v2 ещё не реализован.
- [~] Формализовать RFC 3339 UTC datetime, `YYYY-MM-DD` date и правила округления; полный набор v2 resources ещё не реализован.
- [x] Сохранить совместимые v1 projections.
- [x] Добавить checked-in v2-only OpenAPI snapshot и shared JSON fixtures для Money, Rate, success envelope и Problem Details.
- [x] Нормализовать `application/problem+json` metadata для всех v2 routes через единый OpenAPI helper.
- [x] Добавить frontend Problem Details mapper fixtures и Vitest cases для v2, v1 и fallback payloads.

## Problem Details

- [~] Добавить единый RFC 9457-style envelope с `code` и `requestId`; path-scoped v2 handlers покрывают domain/HTTP/validation/rate-limit/body-size errors, а v1 сохраняет legacy envelope.
- [x] Ввести stable codes для реализованных order/cart/organization surfaces, включая `ORDER_NOT_FOUND`, `PRODUCT_NOT_FOUND`, `PRODUCT_UNAVAILABLE`, `CART_ITEM_NOT_FOUND`, `CART_QUANTITY_OVERFLOW`, `CART_SCOPE_MISMATCH`, `INSUFFICIENT_STOCK`, `STALE_RESOURCE_VERSION`, `IDEMPOTENCY_KEY_REUSED`.
- [x] Ввести typed domain errors и убрать русскотекстовую классификацию в order routes; v1 mapper сохранён совместимым.
- [~] Добавить backend contract tests; shared Problem Details fixtures, frontend mapper fixtures и OpenAPI snapshot проверены, полный cross-client contract ещё не завершён.
- [x] Добавить dependency-free semantic compatibility gate для v2 OpenAPI path/method/parameter/response изменений.

## Создание заявки

- [x] Агрегировать duplicate `sku` в совместимом v1 order-create path; v2-контракт должен дополнительно запрещать duplicate `productId`.
- [x] Добавить `Idempotency-Key`, canonical payload fingerprint и сохранённый result в v1 order-create path.
- [x] Повтор с тем же key и тем же fingerprint возвращает исходную заявку.
- [x] Повтор с тем же key и другим payload возвращает `IDEMPOTENCY_KEY_REUSED`.
- [x] Ввести structured delivery: method, address/pickup, contact, phone, preferred date, comment; v1-compatible старые поля сохранены.
- [x] Проверять availability при create и повторно при manager confirmation; не резервировать stock автоматически.

## Resources и concurrency

- [x] Использовать UUID для client write resources в реализованных v2 order/cart/organization surfaces; SKU остаётся business identifier для показа, поиска и импорта.
- [x] Вернуть media resource `{id, url, width, height, mimeType}` без внутреннего S3 key; cart уже скрывает `photoKey`. Реализовано 2026-09-27: `GET /api/v2/media/{mediaId}` (200 байтами; сначала был 307 на presigned, но mixed content), реестр `media_assets` + backfill миграцией `0020_media_assets`, `thumbnail` в списке и полный `media[]` в карточке. `docs/NATIVE_API_CONTRACT.md` §6.1.
- [x] Добавить `version` и `If-Match` для manager order, cart mutation и repeat writes; v1 без заголовка сохраняет совместимое поведение.
- [x] Возвращать 409 `STALE_RESOURCE_VERSION` при конфликте manager order и cart writes; product/user/admin resources ещё не покрыты.

## Известные migration/runtime риски

- [ ] Проверить `ADMIN` enum на чистой Alembic DB.
- [ ] Backfill исторического `orders.seq` без недетерминированной нумерации.
- [ ] Исправить PDF media type.
- [ ] Проверить ADMIN notification broadcast access.
- [~] Добавить automated legacy migration fixture test: детерминированные UUID/FK, seq, суммы и два legacy-аккаунта с одинаковым `User.company`; отдельный clean Alembic chain по-прежнему проверяется перед релизом.

**Gate:** критические дефекты закрыты тестами; request-not-reservation и price/rate freezing не изменены; v1 не сломан.

# Этап 2. Organization-aware B2B model

**Статус:** `[~]` — expand-only schema, migration, membership-aware context, manager-only v2 organization/member slice и organization-aware catalog/cart реализованы; organization create/patch, reviewed backfill и favorites/exports/cache перенос ещё не завершены.

- [x] Добавить `organizations` и `organization_memberships` с ролями `OWNER`/`BUYER`/`CONTACT`/`VIEWER` и явным `is_active`.
- [x] Добавить organization pricing agreement и organization-brand terms.
- [x] Добавить legal/delivery details и optional delivery points/addresses.
- [x] Перевести владение новыми заявками на organization; сохранить `client_id` как initiator/audit compatibility field и nullable `Order.organization_id` для legacy заявок.
- [x] Реализовать membership-aware context без вывода организации из свободного текста `User.company` и без копирования pricing state в Pinia.
- [x] Реализовать expand-and-contract migration `0013_organization_expand`: nullable additions без автоматического backfill; reviewed backfill и поздний contract ещё не выполняются.
- [x] Не объединять пользователей только по совпадению свободного текста `User.company`.
- [x] Сохранить user-based поля до завершения перехода клиентов; v1 fallback продолжает работать.
- [x] Покрыть membership gating, pricing isolation, order ownership, legacy order access и fingerprint тестами.
- [x] Добавить manager-only v2 list/detail/members/add/patch с CLIENT-only targets, atomic `If-Match` и last-OWNER protection.
- [x] Перевести organization и member lists на DB-level q/sort/keyset cursor с подписанным opaque cursor, `limit+1` и closed sort enums; `total` не возвращается.
- [ ] Добавить organization create/patch и reviewed backfill workflow.
- [x] Перевести catalog и cart на validated organization context с isolated pricing и USER/organization storage.
- [ ] Перевести favorites, exports и cache keys на validated organization context.

**Gate:** организация является границей коммерческого доступа; старые данные не объединены неоднозначно; v1 продолжает работать. Clean Alembic `upgrade head`/`check`/`downgrade` path подтверждён на отдельной базе.

# Этап 3. API v2

**Статус:** `[~]` — добавлены membership-aware session, organization-aware catalog, client cart, order create/list/detail/cancel/repeat, manager organization/member routes, cursor pagination, единый Problem Details OpenAPI helper, frontend mapper fixtures, semantic compatibility gate, v2-only OpenAPI snapshot и shared JSON fixtures; native auth, media, notifications/jobs и полный v2 surface ещё не реализованы.

- [x] Добавить organization/session/current-user contracts: session возвращает `commercialScope`, nullable `organizationId` и memberships; `User.company` остаётся `legacyCompany` и не подменяет membership.
- [ ] Сохранить browser cookie+CSRF flow и добавить native Bearer/refresh grant.
- [~] Реализовать catalog: server-side search/sort/facets/cursor pagination и organization pricing готовы; bulk resolve и media resources отложены.
- [ ] Реализовать media resources без storage keys; v2 cart уже исключает internal `photoKey`.
- [x] Перевести cart в явный USER/ORGANIZATION scope с `version`, `If-Match`/`ETag`, current pricing и v1-compatible USER cart.
- [ ] Перевести favorites в organization scope.
- [~] Реализовать read-only order detail и collection с `{data, meta}`, UUID path, string-money, rate, Problem Details, membership-aware scope, fixed `createdAt,id` keyset cursor и отдельным `OrderSummary` без lines/media; create/cancel/repeat routes реализованы, organization management routes частично реализованы.
- [ ] Реализовать notifications feed/unread state и common async job contract.
- [ ] Реализовать files/exports и manager/admin resources.
- [ ] Заменить presentation-shaped dashboard DTO composable domain queries.
- [x] Сгенерировать v2 OpenAPI из router/schemas и описать Problem Details responses; checked-in v2-only snapshot добавлен и сверяется с `app.openapi()`.
- [x] Добавить semantic diff/export artifact check для изменений v2-контракта.
- [x] Добавить shared JSON fixtures для Money, Rate, order/session/catalog/cart success envelope, cart mutation и Problem Details; frontend mapper fixtures проверяются Vitest.
- [ ] Проверить v1 compatibility projection и deprecation readiness.

**Gate:** v2 contract стабилен для web/Telegram/iOS; v1 не переписан in-place и не блокирует миграцию.

# Этап 4. Frontend domain layer

**Статус:** `[x]` для web-релиза; незавершённые platform-wide v2 ресурсы вынесены в backlog.

- [x] Создать typed API v2 transport и Problem Details mapper с shared fixtures и Vitest-покрытием.
- [x] Подключить session/current-user, organization context и role/channel helpers.
- [x] Выделить server-persisted cart с `userId + commercialScope + organizationId`, ETag/`If-Match`, сериализацией записей и stale-version recovery.
- [x] Выделить order create/list/detail/cancel/repeat слой с UUID, `Idempotency-Key`, replay metadata и повторной загрузкой корзины.
- [x] Централизовать navigation, status registry и presentation formatters.
- [x] Перенести v2 cart consumers и checkout на `useCartV2()`/`useOrdersV2()` без смешивания с legacy `useCart()`.
- [x] Сохранить browser API v2 и Telegram `/m/**` API v1 на раздельных каналах.
- [ ] Выделить favorites, notifications, files/exports и async jobs в полный v2 domain layer — отдельный следующий этап, не блокирует текущий web-релиз.

**Gate:** browser commerce pages используют v2 domain services; page-local business transport не используется.

# Этап 5. Trade Design System

**Статус:** `[x]`.

- [x] Заменить старые rounded/glass tokens на Trade semantic tokens.
- [x] Подключить Manrope и IBM Plex Mono с соответствующими ролями.
- [x] Реализовать light primary и полноценную dark theme.
- [x] Удалить ambient orbs, gradient glow и floating glass surfaces из новых поверхностей.
- [x] Создать прямоугольные Button/Link, Input/Select/Checkbox/Radio и record/table primitives.
- [x] Создать Product record, Price, Quantity, Status, Dialog/Sheet, Toast/Empty/Error/Loading, Order timeline и Sticky action bar.
- [x] Реализовать visible focus, safe-area и status-without-color.
- [x] Проверить отсутствие горизонтального page overflow на 390/430/768/1280.

**Gate:** UI kit соответствует `docs/TRADE_DESIGN_SYSTEM.md` и используется public/client/manager/Mini App.

# Этап 6. Frontend shell

**Статус:** `[x]`.

- [x] Заменить `app.vue` и public/auth/client/manager/miniapp layouts.
- [x] Заменить desktop Header/Sidebar и мобильные Header/Navigation на семантические компоненты.
- [x] Заменить current request popup на server-authoritative v2 flow с `CurrentRequestStrip` и review sheet.
- [x] Сделать `/` постоянным public landing, а `/dashboard` — отдельной client route.
- [x] Нормализовать notifications, profile, security и product links.
- [x] Подключить реальный Toast host.
- [x] Не переносить floating capsule mobile navigation и demo `localStorage` store.

**Gate:** все каналы используют одну Trade design language, сохраняя channel-specific auth и navigation.

# Этап 7. Маршруты

**Статус:** `[x]` для заявленного web-релиза.

- [x] Public/auth: landing, brands/news/legal, login/reset/2FA/consent, error.
- [x] Catalog/commerce: catalog, product, bulk add, favorites, cart, checkout, orders.
- [x] Client account: dashboard, profile, organization, sessions, notifications, security, files.
- [x] Manager/admin: dashboard, catalog, import, orders, organizations/users, files, brands, currency, audit, admin.
- [x] Telegram Mini App: визуальная гармонизация с сохранением отдельной API v1 cart/order логики.
- [x] Проверить основные client vertical slices в браузере: add/update cart, review sheet, cart, checkout, dashboard, orders, profile и product detail.

**Gate:** прежние реальные B2B-сценарии доступны через новую архитектуру; страницы не создают собственный API client.

# Этап 8. Тестирование и rollout

**Статус:** `[x]` — локальные quality gates и production rollout подтверждены.

- [x] Alembic применён до `0018_fix_constraint_drift`; `alembic check` не обнаруживает новых операций.
- [x] API pytest, contract/organization/concurrency/idempotency tests и Ruff проходят.
- [x] Frontend typecheck, ESLint, 12 Vitest files / 95 tests и production Nuxt build проходят под Node 22.
- [x] Выполнен локальный browser smoke основных client routes и v2 cart mutations.
- [x] Выполнены responsive/no-overflow checks на 390/430/768/1280 и keyboard/focus checks Sheet.
- [x] Проверен unauthenticated API v2 Problem Details (`401 AUTHENTICATION_REQUIRED`).
- [x] Выполнить worktree deployment и production smoke на `https://portal-87-232-64-23.nip.io`: landing/login, private-route redirect, marker, mobile overflow, API v2 401 Problem Details, health-check, PM2 и Alembic head подтверждены.
- [ ] После стабилизации web, Mini App и подготовки iOS согласовать deprecation v1; удалять v1 только отдельным этапом.

**Примечание о keyboard smoke:** synthetic DOM Escape закрывает sheet и возвращает фокус триггеру. В IAB нативная доставка Escape через `locator.press`/CUA keypress не сработала; это зафиксировано как ограничение тестового канала, а не подтверждённый браузерный дефект.

**Gate:** production build и ключевые public/client/manager flows проходят; v1/v2 сосуществуют во время rollout.

# Этап 9. iOS после стабилизации web

**Статус:** `[ ]` — implementation намеренно не начата.

- [ ] Зафиксировать API v2/OpenAPI.
- [ ] Сгенерировать Codable fixtures.
- [ ] Создать SwiftUI client modules и tests.
- [ ] Хранить access token в памяти, refresh token — в Keychain; не использовать UserDefaults/logs/analytics.
- [ ] Реализовать native session, 2FA, single-flight refresh и reuse detection.
- [ ] Проверить parity catalog, personalized price, cart, order, status, notifications и documents.
- [ ] Web/PDF facilities использовать только для документов; основной интерфейс не помещать в WebView.

**Gate:** iOS запускается только после стабилизации shared contract и web critical flows.

---

## Ближайшая последовательность

1. [x] Завершить read-only проверку документации и убедиться, что незакоммиченное дерево не затронуто неожиданно.
2. [x] Зафиксировать migration fixture со старой схемой и детерминированными legacy-данными.
3. [x] Сохранить checked-in v2-only OpenAPI snapshot и shared JSON fixtures для Money/Rate/envelope/Problem Details/session/catalog/cart.
4. [x] Расширить v2 transport primitives на session/current-user, catalog, organization, order и cart contracts.
5. [x] Добавить fixtures для frontend Problem Details mapper и semantic breaking-change check.
6. [x] Завершить full regression и migration refusal checks для cart slice.
7. [x] Добавить frontend cart schema/client/repository/store с ETag, scoped invalidation и unit/contract tests; legacy `useCart()` не переключать частично.
8. [x] Добавить typed frontend v2 order-create schema/repository/store/facade с `Idempotency-Key`, replay metadata, scope validation, retry-safe submit и post-order cart refresh.
9. [x] Интегрировать `useCartV2()` и `useOrdersV2()` с browser cart consumers и v2 checkout/order create path.
10. [x] Завершить полную замену web presentation layer, local browser smoke, responsive/accessibility checks и production build.
11. [x] Выполнить worktree deployment и production smoke.

## Текущий статус

Web-релиз полностью переведён на новую Trade presentation и browser API v2 commerce flow. Реализованы public landing/auth, desktop и mobile client shell, catalog, product detail, server-authoritative current request/cart, checkout, orders, profile, manager/admin surfaces и визуально harmonized `/m/**` Mini App. Browser cart изолирован по `userId + commercialScope + organizationId`, использует ETag/`If-Match`, serialized mutations и stale-version recovery. Checkout/order create используют UUID и `Idempotency-Key`; `/m/**` остаётся на отдельном API v1 канале.

Frontend quality gates: typecheck passed; ESLint passed под Node 22; 12 Vitest files / 96 tests passed; production Nuxt build passed. Backend: full pytest passed; Ruff passed; Alembic на `0018_fix_constraint_drift`; `alembic check` passed. Локальный браузер подтвердил add/update cart, request review sheet, cart, checkout, dashboard, orders, profile и product detail, а также responsive/no-overflow на 390/430/768/1280. Главная страница очищена от повторяющейся витринной информации: удалена информационная полоса под header, сокращён hero, а блок «Бренды и номенклатура» теперь перечисляет каждый реальный бренд один раз без SKU и серийных товарных карточек. Каталог в БД не изменяется; детальная номенклатура остаётся на `/brands`. Финальные проверки landing: 1280 и 390 px без horizontal overflow. Временные QA-пользователь, product и brand удалены. Worktree задеплоен на `https://portal-87-232-64-23.nip.io`; production подтвердил 4 реальных бренда, 0 product links в секции, рабочий переход «Открыть весь каталог», `record-v2`, отсутствие горизонтального overflow на 390/1280 px, redirect приватного маршрута, API v2 401 Problem Details, `/healthz=ok`, PM2 online и Alembic head `0018_fix_constraint_drift`.

---

## 2026-09-28 — Этап 1 дорожной карты фич (`docs/FEATURES_ROADMAP.md`): фильтры и поиск в истории заявок

`GET /api/v2/orders` принял опциональные `q`, `date_from`, `date_to`, `min_total`, `max_total` (AND с scope и `status`):
`q` — ILIKE по seq-как-тексту, `notes` и SKU/названию позиций (коррелированный EXISTS по `order_items.product_snapshot`,
спецсимволы LIKE экранируются); даты — включительно, границы суток UTC; суммы — включительно по `total_amount`.
Фильтры входят в подпись cursor'а (`filter_signature`), keyset-пагинация не затронута. v1 не менялся (фронт уже на v2).

Фронт: панель «Фильтры» на `/orders` (поиск с debounce 300 мс, даты, суммы), URL-sync с восстановлением на F5,
счётчик активных фильтров, отдельная заглушка пустого результата, сброс возвращает дефолт вместе со статус-табом.
Схема `orderListQuerySchema` расширена (money — строки до 2 знаков, дата `YYYY-MM-DD`), сериализация в snake_case.

Доки: `docs/API_V2_CONTRACT.md` — секция фильтров коллекции; openapi-фикстура перегенерирована
(`python -m app.scripts.export_v2_contract`); `q` выровнен на 255 символов (бэкенд = фронт).

Проверки: pytest `test_api_v2_orders.py` 13 passed (включая новые: q по номеру/SKU/комментарию, буквальность
wildcard, включительность диапазонов, привязка фильтров к курсору, 422 на мусорный формат); `test_contract_artifacts.py`
+ `test_api_v2.py` 14 passed. Web: vitest 18 файлов / 150 тестов passed, typecheck 0, ESLint 0 (Node 22).
GUI-обход локального стенда (IAB, сессия куками): рендер панели, поиск по номеру и по SKU, заглушка пустого
результата, `min_total=25` → только З-000262, F5 восстанавливает `q`+`min_total` со счётчиком «2», мобильная
375px — поля в колонку без наложений. Кнопочные клики и очистка поля клавиатурой в IAB-автоматизации не
проходят (известный кварк стенда, не страницы) — пути покрыты юнит-спекой `orders-filters.spec.ts`; снятие
фильтра вводом проверено через пробел (trim → фильтр снят, URL очищен). Не закоммичено; деплой — по команде.

---

## 2026-09-28 — Этап 2 дорожной карты фич: адресная книга доставки

Backend v2: новый роутер `/api/v2/me/organization/addresses` (GET/POST/PATCH/DELETE). Чтение — любой
активный участник организации; запись — OWNER/BUYER (`403 ADDRESS_FORBIDDEN`). POST требует
`Idempotency-Key` (422 без него) и идемпотентен по natural key: повтор того же `(kind, addressLine)`
возвращает существующий адрес с 201 — без key→result-хранилища, конвергенцию даёт unique constraint
0013. PATCH: absent сохраняет значение, явный null у nullable-полей очищает (model_fields_set), null
у kind/addressLine/countryCode → 422; смена kind/addressLine на занятые → 409 ADDRESS_DUPLICATE.
isDefault уникален в рамках kind (транзакционный сброс чужих флагов). Без организации: GET → [],
POST → 409 NO_ORGANIZATION. Заказ: `delivery.addressId` валидируется на принадлежность организации
(`404 ADDRESS_NOT_FOUND` через `OrderAddressNotFoundError`), в заявку пишутся id и снапшот-строка
`delivery_address` (address_line, city, postal_code через «, »). Миграция не потребовалась.

Frontend: zod-схемы (`organizations.schema.ts`), `domain/organization/organization.repository.ts`,
composable `useOrganizationAddresses`; checkout получил адресную книгу: радио-карточки сохранённых
адресов (default предвыбран, бейдж «По умолчанию»), форма нового адреса с чекбоксом «Сохранить в
адресную книгу», деградация к тексту в комментарии, если книга недоступна; бейдж дефолта поднят с
10px до text-xs по дизайн-контракту. Исправлены мутация общего fixture в спеке и типизация.

Доки: §7 API_V2_CONTRACT «Address book» + NATIVE_API_CONTRACT «Address book (checkout delivery)» —
сведены к фактической реализации; openapi-фикстура перегенерирована, paths добавлены в
contract-артефакты.

Проверки: pytest 29 passed (адреса ×9, включая null-очистку/403/404/идемпотентность/чужой адрес;
создание заказа с реальным снапшотом адреса; контрактные артефакты; v2). Web: vitest 20 файлов /
164 теста, typecheck OK, ESLint (Node 22) OK. Живой интеграционный прогон на стенде: адрес → заказ
263 с delivery.addressId и снапшотом «ул. Притыцкого, 12, офис 305, Минск» в ответе и в БД.
GUI-клики в IAB-стенде по-прежнему не проходят (радио-переключение Delivery недоступно автоматизации;
логика UI покрыта checkout-address.spec.ts). Менеджерская read-only витрина адресов отложена: менеджер
не член организации, по контракту адреса ему недоступны — нужен отдельный manager-эндпоинт (след. этап).
Не закоммичено; деплой — по команде.
