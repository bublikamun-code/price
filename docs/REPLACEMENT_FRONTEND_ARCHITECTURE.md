# Replacement Frontend Architecture

> Канон замены `apps/web`, утверждён 2026-09-24. Он описывает новый production frontend, а не HTML-прототип `price-web-samples`.

## 1. Решение

Frontend заменяется полностью в существующем Nuxt-приложении. Это не CSS reskin и не последовательная перекраска старых page templates.

Заменяются:

- page templates и route-specific presentation;
- layouts и application shell;
- общие UI primitives;
- локальные API orchestration, polling и DTO parsing из страниц;
- page-local type extensions и presentation-shaped adapters;
- rounded/glass/Liquid Glass visual system.

Сохраняются через извлечение и развитие:

- SSR и Nuxt infrastructure;
- API/session plugins как основа нового typed client;
- single-flight refresh и one retry;
- CSRF propagation для browser cookie session;
- server-persisted cart;
- optimistic favorites с rollback;
- notification SSE и polling fallback;
- catalog request sequencing;
- URL-backed catalog state;
- role/channel middleware concepts.

Статический прототип остаётся visual reference. Его HTML, CSS, JS, `localStorage` и demo auth не попадают в production runtime.

## 2. Граница с backend

Backend не заморожен, но его проверенное ядро не переписывается ради cosmetic redesign.

Сохраняются:

- FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery, MinIO;
- refresh rotation и reuse detection;
- CSRF, session revocation, RBAC, 2FA и consent;
- pricing formula, fixed/NBRB rate и order snapshots;
- order FSM и audit log;
- CSV/photo import, rollback, exports и async jobs.

Меняются только необходимые контракты и доменные границы:

- API v2 и стабильные ошибки;
- organization ownership;
- единое представление денег и дат;
- order idempotency и structured delivery;
- UUID для write resources;
- media resources без S3 keys;
- cursor pagination, server search/sort;
- native session flow;
- optimistic concurrency.

## 3. Целевая структура

```text
apps/web/
├── app.vue
├── layouts/
│   ├── public.vue
│   ├── auth.vue
│   ├── client.vue
│   ├── manager.vue
│   └── miniapp.vue
├── pages/
├── components/
│   ├── ui/
│   ├── layout/
│   ├── catalog/
│   ├── orders/
│   ├── manager/
│   └── notifications/
├── domain/
│   ├── api/v2/
│   ├── auth/
│   ├── organization/
│   ├── catalog/
│   ├── cart/
│   ├── orders/
│   ├── notifications/
│   ├── jobs/
│   ├── files/
│   ├── formatting/
│   └── navigation/
├── stores/
├── composables/
├── middleware/
├── plugins/
├── types/
├── utils/
└── tests/
    ├── unit/
    └── contract/
```

`domain/` содержит независимые от Vue templates модули. Composables подключают их к Nuxt lifecycle; Pinia stores хранят долговременное состояние. Page component получает prepared view model и вызывает domain commands, но не знает URL, JSON parsing, polling loop или error-code mapping.

## 4. Слои

### 4.1 Transport layer

Ответственность:

- base URL `/api/v2`;
- browser credentials и CSRF;
- Bearer session для native-compatible clients;
- typed request/response parsing;
- timeout и cancellation;
- single-flight refresh;
- Problem Details mapping;
- request id propagation.

Transport не содержит page state и не форматирует UI.

### 4.2 Domain services

Примеры:

- `CatalogRepository`: products, facets, bulk resolve;
- `CartRepository`: server cart and mutations;
- `OrderRepository`: draft/create/detail/list/cancel/repeat;
- `SessionRepository`: login, refresh, current user, sessions;
- `NotificationRepository`: feed, read state, stream URL;
- `JobRepository`: common async job status;
- `OrganizationRepository`: current organization and manager resources.

Domain service не зависит от `AppHeader`, toast или route. Он возвращает typed values и stable domain errors.

### 4.3 Stores

Хранят состояние, которое переживает navigation:

- session/current user;
- active organization;
- cart summary;
- catalog query and request state;
- notifications;
- async jobs, за которыми пользователь наблюдает;
- theme and navigation preferences.

Derived values вычисляются store/computed, а не дублируются в template.

### 4.4 Presentation

Page templates отвечают только за:

- layout нужной функциональной группы;
- выбор компонента по состоянию;
- локальное состояние формы, не меняющее server resource без domain service;
- submit intent и навигацию.

## 5. API clients

### 5.1 Статические типы

После стабилизации OpenAPI v2 генерируется checked-in client/types artifact. До этого доменные типы живут в одном месте, а page-local intersections и `as unknown as` запрещены.

DTO не содержат UI-ready percent strings, preformatted prices или quick actions.

### 5.2 Problem Details

Transport преобразует RFC 9457-style response в `AppProblem`:

```ts
type AppProblem = {
  code: string
  title: string
  detail: string
  status: number
  requestId?: string
  fieldErrors?: Record<string, string[]>
  retryable: boolean
}
```

UI выбирает текст по `code`; backend detail остаётся fallback/diagnostic context.

### 5.3 Money и date

- Money — decimal string + ISO 4217 currency: `{ amount: "123.45", currency: "BYN" }`;
- date — `YYYY-MM-DD`;
- datetime — RFC 3339 UTC, например `2026-09-24T14:30:00Z`;
- decimal/rate не принимает JSON float в v2.

## 6. Browser и native sessions

Browser:

- httpOnly cookies;
- CSRF token для cookie-auth mutations;
- refresh rotation и session metadata.

Native-compatible session:

- access token в Bearer header;
- refresh token в response body только для явно native/non-cookie session grant;
- refresh rotation и reuse detection сохраняются;
- device name, OS, app version и last-used metadata сохраняются в session record;
- endpointы login/refresh/logout различают `client_type: WEB|NATIVE|TELEGRAM`.

Telegram получает собственный grant, но после аутентификации использует те же domain resources.

## 7. Catalog query

URL является единственным источником catalog query state:

```text
/catalog?q=...&brand=<uuid>&series=<uuid>&stock=IN_STOCK&sort=sku:asc&view=table&cursor=<opaque>
```

- SSR читает URL и передаёт типизированный query в repository;
- client navigation изменяет URL, watcher запрашивает новую страницу;
- каждый запрос получает sequence id; stale response игнорируется;
- AbortController отменяет предыдущий запрос;
- facets и total приходят одним response/meta contract;
- page-size changes сбрасывают cursor;
- filter serialization, parsing и sorting unit-tested.

## 8. Cart и order draft

Cart — server resource с явным commercial scope: один legacy USER cart и независимый cart для каждой organization. Store/repository получает UUID и version из ответа, а body mutation не принимает произвольный `organizationId`.

Cart client/repository:

- `GET /cart` загружает текущую scoped cart и сохраняет `ETag`;
- `POST /cart/items` инкрементирует line, `PUT /cart/items/{productId}` заменяет quantity/note, `DELETE` удаляет line или очищает cart;
- каждая mutation передаёт `If-Match` с последней version, а success response атомарно обновляет cart и ETag;
- `STALE_RESOURCE_VERSION` переводит store в conflict state, затем refetch; optimistic quantity никогда не превращается в silent overwrite;
- user/organization switch инвалидирует cart query и pending requests, чтобы данные scope не смешивались;
- `totalItems` отображается как число lines, а не сумма quantity;
- media/storage keys не попадают в domain DTO.

Favorites и bulk-add остаются отдельными resources. Когда bulk-add появится, SKU допускается только как input resolver, а cart mutation использует product UUID.

Create order:

- checkout создаёт/использует draft id;
- final submit получает новый `Idempotency-Key` из domain service;
- double click и retry используют тот же key для той же fingerprint;
- server возвращает исходный order при повторе;
- `IDEMPOTENCY_KEY_REUSED` не смешивается с network error;
- structured delivery валидируется до submit.

## 9. Notifications

- initial unread count и feed загружаются domain service;
- SSE запускается после session ready;
- reconnect переходит на controlled backoff;
- stream error переключает на polling fallback;
- logout/user switch закрывает stream и очищает stores;
- browser EventSource использует cookie session; native client получает поддерживаемый transport или polling fallback.

## 10. Async jobs

Общий контракт:

```ts
type AsyncJob = {
  id: string
  kind: 'CATALOG_EXPORT' | 'ORDER_PDF' | 'PRICE_IMPORT' | 'PHOTO_ZIP' | 'FILE_UPLOAD'
  status: 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED' | 'CANCELLED'
  progress?: number
  result?: { downloadUrl?: string; expiresAt?: string }
  error?: { code: string; message: string }
  createdAt: string
  updatedAt: string
}
```

UI не содержит собственный copy polling loop. `JobService` выполняет bounded polling/backoff, а store отображает состояние.

## 11. Route and channel shells

- `/` всегда public landing;
- `/dashboard` — client;
- `/manager` — manager/admin;
- `/m/**` — только Telegram surface;
- public, auth, client, manager и miniapp layouts не переключают назначение маршрута по auth state.

Авторизованный пользователь, открывший `/`, видит landing; после login его маршрут определяется ролью.

## 12. SSR и hydration

- public pages используют server-side public projections;
- client pages требуют session-aware SSR без кэширования private HTML;
- auth restore выполняется plugin один раз;
- server data получает request-scoped keys;
- theme и browser-only data не создают hydration mismatch;
- mobile channel определяется route/layer, а не шириной окна на первом render.

## 13. Тестирование

### Unit

- URL query serialization;
- money/date formatting;
- problem-code mapping;
- status registry;
- cart line merge;
- idempotency key lifecycle;
- request sequencing;
- role/channel navigation.

### Contract

- shared JSON fixtures for API v2;
- OpenAPI validation and semantic diff;
- browser/native/Telegram auth projections;
- money always decimal string;
- UUID writes;
- Problem Details codes.

### Component

- forms, tables, dialogs, sheets, status badges, async job state;
- keyboard/focus behavior;
- no horizontal overflow at 390 px.

### E2E

- landing → login → consent → catalog;
- catalog filter/search/sort/pagination;
- product → cart → idempotent checkout → order detail;
- repeat/cancel/status;
- manager organization/order update with stale version;
- import/export job;
- notifications reconnect;
- role guards.

## 14. Канальная композиция

Производственный frontend имеет четыре разных channel shell, но одну Trade visual language:

| Surface | Layer | Commerce API | Primary hierarchy |
|---|---|---|---|
| Browser client | `client.vue` | v2 | Catalog, current request, cabinet, profile |
| Public/auth | `public.vue` / `auth.vue` | public v1 projections + auth v1 | editorial landing и последовательный auth flow |
| Manager/admin | `manager.vue` | v1 | service navigation, KPI records, dense tables |
| Telegram Mini App | `miniapp.vue` | v1 | Telegram auth, product records, request, orders, notifications |

Browser client route templates не содержат собственного header, bottom navigation или request shell: они предоставляются `client.vue`. Каталог, заявка, checkout, кабинет, история и профиль меняют содержимое рабочей области, но используют общие `ProductRecordRow`, `OrderLineRecord`, `CurrentRequestStrip`, `RequestReviewSheet`, `StickyActionBar` и `PageHeading`.

Desktop client/manager surfaces могут использовать sidebar и таблицы, но mobile compositions строятся как record/list, а не уменьшенная копия desktop. `390`, `430`, `768` и `1280` px являются проверяемыми acceptance widths. Mobile action не может быть ниже 44 px, а page не должна иметь горизонтальный overflow.

Визуальная миграция не изменяет channel ownership:

- browser cart остаётся server-authoritative v2 resource с owner scope, ETag/`If-Match`, mutation serialization и conflict recovery;
- order create/repeat остаётся idempotent и version-aware;
- manager workflows остаются v1 и сохраняют RBAC, FSM, polling, rollback и export endpoints;
- Mini App остаётся v1, использует `useCart()` и Telegram `initData`, не импортирует `useCartV2`;
- public landing и auth не инициируют client cart и не загружают private client data.

## 15. Порядок rollout

1. Shared shell and public/auth.
2. Catalog and product.
3. Cart, checkout and client orders.
4. Client account/dashboard.
5. Manager organizations/users/catalog/orders.
6. Manager import/files/currency/audit/admin.
7. Telegram Mini App shell.
8. Remove or delete superseded frontend components after each route has coverage.

API v1 остаётся доступным для старых Mini App и внешних клиентов. V2 удаляется или переводится в deprecated только отдельным этапом после миграции всех каналов.
