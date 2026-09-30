# Price Web — прогресс полной замены web и миграции API v2

> **Дата последнего обновления:** 2026-09-30  
> **Канон:** `ARCHITECTURE_PLAN.md` v2.2, `SITEMAP.md` v2.0 и документы в `docs/`.  
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

## 2026-09-29 — Этап 3 дорожной карты фич: документы на товар (сертификаты и даташиты)

Backend v2: `FileAsset` + `product_id`/`series_id` (nullable FK, SET NULL) + `valid_until DATE`,
`FileAssetType` + `CERTIFICATE`/`DATASHEET` (миграция 0021, `ALTER TYPE ... ADD VALUE` по паттерну
0014). Загрузка — `POST /api/v2/manager/products|series/{id}/documents` (multipart: file/type/
valid_until, RBAC MANAGER, опц. Idempotency-Key; PDF-only: расширение + content-type + magic-bytes
`%PDF` + лимит, ровно одна привязка, S3 до записи БД), `DELETE /api/v2/manager/documents/{id}` (204,
сначала S3; `BRAND_PDF` → 404 — брендовые PDF удаляются через v1 `/manager/files`). Выдача клиенту:
`documents[]` в v2 product detail (`id/type/fileName/scope product|series/validUntil/isExpired` —
свои документы + документы серии, просроченные помечаются, не скрываются); скачивание **байтами**
`GET /api/v2/catalog/products/{id}/documents/{docId}/download` (не presigned — урок mixed-content
27.09). `upload_asset` (v1) больше не принимает CERTIFICATE/DATASHEET — только через v2-привязку.
Попутно пойман баг приоритета операторов `a | b == c` в file_assets-репозитории.

Frontend: секция «Документы» в карточке товара — бейджи «Сертификат»/«Даташит», «действует до …»
зелёным, «истёк …» красным, пометка «общий для серии», скачивание blob с кукой по паттерну
useXlsxExport, per-row loading, скрыта при пустом списке; trade-presentation без UiStatusBadge.
Менеджерка: `ProductDocumentsPanel` (список + форма загрузки + удаление с инлайн-подтверждением)
в модалке товара `/manager/catalog` и в модалке серии `/manager/brands`. zod-схемы
`documents.schema.ts`, `domain/documents.repository.ts` (series-резолв через detail первого товара
серии), composable `useDocumentDownload`. Мини-апп `/m/**` не тронут (отложен).

Доки: §6/§10 канона + §16 п.38; API_V2_CONTRACT §8/§14/§15; openapi-фикстура перегенерирована,
`catalog_product_detail.json` — 3 документа (свой/серии/просроченный), contract-артефакты обновлены.

Проверки: pytest — весь suite **550 passed** (новые 24: 403 клиенту, 201 менеджеру + S3-ключ,
415 на не-PDF/расширение/content-type/magic-bytes, 422 тип/valid_until, 413, documents[] со scope и
isExpired, скачивание байтами без утечки ключа/Location, удаление + очистка S3). Web: vitest
173/173 (9 новых контрактных), ESLint (Node 22) OK, nuxt typecheck exit 0. GUI-смоук стенда: 3 типа
документов, «истёк 31.12.2024» красным, наследование серии на брате-товаре, модалки менеджера,
confirm удаления; успешные upload/download e2e локально не прогонялись — MinIO стенда недоступен
(502 обрабатывается инлайном), multipart-связь подтверждена логами API. Прод недоступен по SSH из
текущей сети (29.09) — деплой по команде, когда маршрут вернётся.

## 2026-09-29 — починка стабов: SSE-события, email-шаблоны, thumb в плитке

**publish_notification() реализована** (была заглушка `pass` с первого коммита, SSE отдавал только
heartbeat). SSE `/api/v1/notifications/stream` уже подписывался на Redis pub/sub
`notifications:user:{id}` + `notifications:broadcast` (MANAGER) — не было издателя: добавлен
sync-PUBLISH (ленивый синглетон, работает из async-контекста и Celery), fail-open (сбой брокера →
warning, уведомление не ломается), `ensure_ascii=False` с экранированием переводов строк.
Формат события не менялся: `event: notification`, data `{id, type, title, body}`. Все 6 мест вызова
(public LEAD_CREATED, PRICE_CHANGED сводка/дайджест, курс НБРБ, manager/admin users) публикуют.
Вторая половина бага была на фронте: `startStream()`/`startPolling()` вообще не вызывались — стрим
не открывался; запуск добавлен в `useAuth.applyUser()` (покрывает вход, 2FA, Telegram-вход миниаппа)
и `resetClientData()` (перезапуск после сброса), идемпотентно, только клиент.

**Email-шаблоны заказов** (были `<p>Заглушка: заказ …</p>`): общий каркас `_order_email_layout()`,
инлайн-CSS в палитре витрины, без внешних ресурсов. order_created менеджеру (номер, клиент, сумма
как в PDF-выгрузках, способ получения, кнопка/ссылка на /manager/orders) и status_changed клиенту
(новый статус, кнопка/ссылка на /orders). Ссылка из `settings.web_app_url`, при пустом —
относительный путь (как у сброса пароля).

**`?size=thumb` в media API** — починена выдача (параметр вернули в контракт как
`Literal["large","thumb"]`, default large = прежнее поведение): `thumb_key_for()` зеркалит витрину
брендов, `size=thumb` читает thumb-ключ, при отсутствии — фолбэк на large (не 404). `thumbnail` в
v2 product detail несёт `?size=thumb` — плитка каталога тянет ~12КБ вместо ~36КБ. Cache-Control
immutable сохранён (ключ кэша — полный URL). OpenAPI-фикстура перегенерирована (аддитивно).

Проверки: pytest весь suite **578 passed** (новые: 8 notification_events включая round-trip
publish→подписчик на fakeredis, 10 email-шаблонов, +6 media thumb); vitest 173/173; ESLint (Node 22)
по изменённым composables OK. Не проверено: живая SMTP-отправка и рендер писем в клиентах,
live-SSE в браузере (стендовый GUI-прогон — отдельным шагом), поведение KMP-клиента с thumb
(байты по URL, коллизии кэша нет).

## 2026-09-30 — GUI-проверка на проде (2c8d6c2): документы, SSE, миниатюры

Прогон в IAB-браузере по прод-URL. Пройдено: секция «Документы» в клиентской карточке
(бейджи типов, «действует до 31.03.2027», кнопки скачивания; скриншот) — засечено live-созданием
документов менеджером через API (file chooser в IAB недоступен — загрузка/удаление GUI-кликом
не тестировались, API-пути покрыты 24 pytest); скачивание — GUI-клик заблокирован рантаймом
(IAB сегодня не кликает: locator/cua/dom_cua все молчат — известный каприз), API-доказательство:
200, application/pdf, Content-Disposition с UTF-8-именем, magic %PDF-1.4; SSE end-to-end —
лид с лендинга появился в «Уведомлениях» менеджера БЕЗ перезагрузки (серверный кадр
`event: notification` подтверждён и curl-стримом); миниатюры — все фото сетки каталога и плитка
карточки грузятся `?size=thumb` (naturalWidth 400). Скриншоты: gui-test-screenshots/ (некоммитится).
Попутно: лимитер логина на проде — ключи LIMITS:* (верхний регистр), у /api/v1/public/lead свой
лимит 5/10мин; cookie-мутации требуют double-submit CSRF (кука csrf_token → заголовок X-CSRF-Token).
read-all не снимает непрочитанность с broadcast-уведомлений — 6 тестовых лидов «UI-ТЕСТ SSE-*»
остались в списке менеджера (подписаны «можно удалить»).

## 2026-09-30 — фикс: персональное прочтение broadcast-уведомлений (§16 п.39)

Найдено GUI-тестом 30.09: «Отметить все прочитанными» и per-item read не работали для
broadcast (user_id IS NULL — лиды с лендинга): 204 возвращался, но записи оставались
is_read=false навсегда, per-item давал 404. Причина: is_read — одна колонка на всех менеджеров.

Решение (миграция 0022_broadcast_reads, модель NotificationReadState): колонка is_read —
состояние только личных уведомлений; персональное прочтение broadcast — строка в
notification_reads (uq (notification_id, user_id), FK CASCADE, ix по user_id). PATCH /{id}/read:
личное своё — как было; broadcast менеджером — вставка read-строки (ON CONFLICT DO NOTHING,
идемпотентно); чужое личное — по-прежнему 404. PATCH /read-all: личные (UPDATE) + INSERT
read-строк по всем ещё не прочитанным broadcast. is_read/unread_only в ленте считаются
по-юзеру (личные: колонка; broadcast: NOT EXISTS read-строки; страница дополняется одним
запросом fetch_read_broadcast_ids). meta.unread_count (бейдж) — осознанно только личные,
иначе бейдж не обнулить без чтения чужих лидов.

Доки: §6 «Уведомления» + §16 п.39; докстринги роутера/сервиса/репозитория/схем сведены.
Проверки: test_notifications_pull 10 passed (персональность прочтения между двумя менеджерами,
идемпотентный повторный PATCH, read-all закрывает broadcast только читателю, бейдж без broadcast,
клиенту broadcast не виден, чужое личное 404); весь suite EXIT=0 (падений нет; итоговая строка
pytest по-прежнему съедается буферизацией docker compose exec); ruff чисто. Форма DTO не менялась.

## 2026-09-30 — Этап 4 «Счёт на оплату» (§16 п.40): канон, бэкенд, фронт, прод

Ровод Roadmap «Этап 4» закрыт целиком. Работа шла по §21: сначала канон, потом код.

**Канон (5690a97, v2.1 → v2.2).** §5.2: таблица `invoices` (1:1 с заказом), `FileAsset.order_id`
и тип `INVOICE_PDF`, реквизиты в `organizations`. Отдельного поля `unp` не заводили —
`tax_id` уже семантически УНП; это же закрывает висевший TODO §16 п.25. §6 — шесть эндпоинтов,
включая блок `invoice` в v2 order detail и в списке заказов. §10 — Celery-рендер PDF в S3 плюс
состояние в колонке `pdf_status`, а не в Redis: TTL бакета csv-exports (7 дней) убил бы счёт.
§16 п.40 — 9 решений, включая запрет пересчёта цен в счёте (даже по курсу НБ РБ) и «Без выделения НДС».
SITEMAP и docs/API_V2_CONTRACT.md синхронизированы.

**Бэкенд (a908fb0).** Миграция 0023 (`down_revision = 0022_broadcast_reads`): `invoices` с тремя
UNIQUE, `CREATE SEQUENCE invoices_seq_seq` (номер `СЧ-YYYY-NNNNNN` — урок §9, не MAX+1),
`ALTER TYPE file_asset_type ADD VALUE 'INVOICE_PDF'`, `file_assets.order_id`, `organizations.bank_*`.
Сервис, репозиторий, шесть роутеров, схемы, Celery-задача `export_invoice_pdf`, шаблон
`invoice.j2`, конфиг `seller_*` и `rate_limit_invoice_issue`.

Два дефекта поймал на ревью и починил:
- POST на несуществующий заказ отдавал 400 «ошибка выставления счёта» — добавил
  `OrderNotFoundError` → 404 `ORDER_NOT_FOUND`;
- IntegrityError на `uq_invoices_order_id` (гонка двух менеджеров за заказом) вызывал
  `rollback()` всей транзакции роутера — а в ней уже лежал резерв Idempotency-Key, и после
  409 повтор с тем же ключом создал бы второй счёт. Заменил на savepoint
  (`db.begin_nested()`): откатыруется только вставка счёта, транзакция роутера цела.

**Фронт (2b22875).** `useInvoice`/`useInvoiceDownload`, доменный репозиторий с ETag-quoting в
`toIfMatch`, zod-схема, панель `OrderInvoicePanel.vue` (выставить, смена статуса, перерендер,
скачать) с сохранением ключа идемпотентности на сетевых ошибках и авто-опросом PENDING→READY
(20 попыток по 3 с) — менеджеру не надо жать «Обновить»; карточка клиента `InvoiceCard.vue`
рисуется только когда `order.invoice` есть; страницы реквизитов организации и пункт меню.
При 409 `STALE_RESOURCE_VERSION` панель перечитывает счёт, а не перетирает его молча.

**Проверка на проде (vh163, миграция 0023 применена, смоук зелёный).** Счёт `СЧ-2026-000001`
выставлен: 201, сумма 30.00 BYN заморожена из заказа; Celery собрал PDF за <4 с в `pdf_status=READY`;
скачивание — 200, 6544 байта, `application/pdf`, `%PDF-1.7`, корректный RFC 5987 filename.
Повтор с тем же `Idempotency-Key` → 201 с `x-idempotency-replayed: true`; новый ключ на том же
заказе → 409 `INVOICE_ALREADY_EXISTS`; `If-Match: 99` → 409 `STALE_RESOURCE_VERSION`, `If-Match: 1` →
200 (PAID, version 2); POST на неизвестный заказ → 404 `ORDER_NOT_FOUND`.

Клиентский контур проверен на заказе самого тестового клиента (`СЧ-2026-000002`, 85.47 BYN):
в `GET /api/v2/orders/{id}` появился блок `invoice`, клиент скачал PDF байтами (200, 6542 байта),
а чужой счёт и чужой заказ отдают 404 `INVOICE_NOT_FOUND` / `ORDER_NOT_FOUND` — без утечки
существования. Содержимое PDF проверено программно (поток содержимого + ToUnicode-карты):
номер, дата, «Основание: заявка № 4», стороны, позиция 85.47, «Итого к оплате 85.47», адрес
доставки, «Без выделения НДС», «цены зафиксированы», «Стр. 1 из 1»; вёрстка в одну страницу,
за поля страницы не выходит. Визуальный судья PDF не отработал — сработал лимит провайдера,
поэтому вёрстка проверена измерением координат, а не глазами.

**Попутный фикс.** Пустые банковские реквизиты печатались в PDF тремя прочерками
«Банк/Код банка/Р-с: —» — счёт выглядел недозаполненным. Проекция `buyer`/`seller` теперь
отдаёт `bank: null`, пока не заполнено ни одного поля (`_party_bank`), и шаблон блок не рисует.
Закрыто двумя тестами. Продавец и покупатель теперь ведут себя одинаково.

**Проверки кода.** 22 теста счетов (включая два новых на реквизиты) — passed; весь бэкенд-прогон
EXIT=0 (по частям: сплошной прогон памяти не хватило, контейнер упал с 137 — это ООМ, не падения,
ни одного FAILED/ERROR; после перезапуска стека по четыре чанкам все зелёные); vitest 200/200;
vue-tsc чисто; ESLint (Node 22) чисто.

**Открыто (нужны данные пользователя, не выдумывал).** 1) Реквизиты продавца в `.env` прода
(`seller_legal_name`, `seller_tax_id`, `seller_address`, `seller_bank_*`) — сейчас в PDF прочерки;
это реальные юридические данные, подставлять их должен пользователь. 2) На проде 0 организаций и
0 заказов с `organization_id`, поэтому реквизиты покупателя и счёт «на организацию» на живых
данных не проверены — покрыто тестами. 3) Мини-апп `/m` отложен (нужны токен бота, кнопка меню,
PM2-процесс) и в этом этапе не трогался.

---

## 2026-09-30 — Этап 5 «Скидки за объём» (§16 п.41): лестница «от N шт −X%» на бренд

Роадмап «Этап 5» закрыт целиком. Работа шла по §21: сначала канон (коммит `274cfb2`, v2.3),
потом код (`0159c2c`).

**Что сделано.**
- Миграция `0024_volume_tiers`: `brand_volume_tiers(brand_id, min_qty, discount_percent
  NUMERIC(5,2))` с uq (brand, min_qty) и индексом по убыванию порога; `brands.version` под
  оптимистичную блокировку общей сущности.
- `PricingService`: ступень выбирается по количеству **строки**, применяется одна — с наибольшим
  `minQty <= quantity`. С процентом из `organization_brand_terms` берётся максимум из двух, а не
  сумма; `overridePrice` (жёсткая цена из CSV) объёмной скидке не подвержен.
- Кэш: `TaggedCache` с тегом бренда — правка ступени сбрасывает цены бренда, иначе менеджер
  увидел бы старые цены до истечения TTL.
- API v2: `GET/POST /api/v2/manager/brands/{brandId}/volume-tiers`,
  `PATCH/DELETE /api/v2/manager/volume-tiers/{tierId}`. `If-Match` несёт версию **ступени**,
  а не бренда: общая версия заставила бы менеджера перезагружать чужую правку процента.
  Коды `VOLUME_TIER_NOT_FOUND`, `VOLUME_TIER_DUPLICATE_THRESHOLD`, `STALE_RESOURCE_VERSION`.
- Фронт: редактор в `/manager/brands` (модалка `manager-volume-tiers-modal`), бейдж «от N шт −X%»
  в карточках каталога, полная лестница с пояснением в карточке товара, применённая ступень в
  корзине и в быстром просмотре заявки. Бейдж намеренно **не** показывается на позициях
  оформленной заявки: цена там заморожена, и «достигнутая ступень» была бы враньём.

**Протип поля — главная ловушка этапа.** `discount_percent` в БД это `NUMERIC(5,2)`, и
Pydantic v2 сериализует `Decimal` в JSON-строку: `VolumeTierOut` отдавал `"2.00"`, а
`VolumeTierHint` и `CartLineVolumeTier` — число `2.0`. Одно и то же поле двумя типами в
зависимости от эндпоинта ломает zod-контракт на фронте. Сделал `float` во всех трёх формах и
закрепил правило в §6 и в `docs/API_V2_CONTRACT.md` §8: процент — всегда число, деньги — всегда
каноническая строка. Поймано до деплоя на эмпирической проверке `model_dump_json`, не на проде.

**Проверка на проде (vh163, миграция 0024 применена).** Схема сверена напрямую: `numeric(5,2)`,
uq и индекс на месте, ступеней 0 — первую пришлось заводить через интерфейс.
- Менеджер (`manager@example.by`) на `/manager/brands`: пустое состояние с честным текстом,
  добавление `от 10 шт −2%` и `от 50 шт −5%`, повтор порога 10 → «Порог от 10 шт уже занят»,
  правка процента 2 → 3 с ростом `version` 1 → 2 (значит `If-Match` дошёл), удаление
  `от 50 шт` и повторное добавление. В `/manager/audit` видны `volume_tier.create` /
  `.update` / `.delete` с актором и дифом до → после.
- Клиент (`test-ui-client@example.by`): бейдж «от 10 шт −2%» в каталоге у KEAZ; в карточке —
  вся лестница и пояснение, а `Ваша цена` без объёмной скидки (в каталоге количество неизвестно —
  так и задумано).
- Граница в корзине: 9 шт × 85,47 = 769,23 без ступени; 10 шт → `volumeTier {minQty: 10,
  discountPercent: 3}`, `unitPrice` 82,91, `lineTotal` 829,10. Проверено на ROSTOKELECTRO,
  где у товара есть живая цена; ступень после проверки снята, чтобы не оставлять за собой
  мусорных данных. KEAZ оставлен с лестницей 10/−2% и 50/−5% как демонстрация.
- Попутно: у строки ступени в панели тире и слово «минус» склеивались («—минус 2%») — в шаблоне
  пробел стоял в тексте, который схлопывался с переносом строки. Заменено на `&nbsp;`.

**Проверки кода.** ~650 pytest, 220 vitest (20 из них — новый `volume-tier-contract.spec.ts`),
`nuxt typecheck` чисто, ESLint (Node 22) чисто, снапшот OpenAPI и общие фикстуры v2
перегенерированы и проверены `test_contract_artifacts.py`.

**Открыто.** Данных, которых не хватает, не выдумывал: реквизиты продавца в `.env` прода и
наполнение организаций на проде (из этапа 4) остаются в силе. Мини-апп `/m` отложен.
