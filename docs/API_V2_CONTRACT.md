# API v2 Contract

> Рабочий контракт миграции. Утверждён как направление 2026-09-24; финальные OpenAPI-схемы должны быть сгенерированы из реализации и проверены fixtures/diff.

## 1. Стратегия версий

- `/api/v1/**` продолжает работать и не переписывается in-place.
- Новый replacement frontend использует `/api/v2/**`.
- Mini App и новый iOS получают один cross-client contract v2.
- V1 получает compatibility projections во время organization migration.
- V1 deprecation/removal — отдельное согласованное решение после миграции всех клиентов.

## 2. Базовые правила

- base path: `/api/v2`;
- JSON: UTF-8, `camelCase`;
- UUID — RFC 4122 string для всех write resources;
- SKU — visible/searchable/importable business identifier, не write identity;
- timestamps — RFC 3339 UTC;
- date — ISO `YYYY-MM-DD`;
- money — decimal string + ISO 4217 currency;
- rate — decimal string with scale and source;
- lists — opaque cursor pagination по умолчанию;
- filters/sort/search выполняются сервером;
- client `meta` не содержит presentation-ready labels или formatted business data.

## 3. Success envelope

```json
{
  "data": {},
  "meta": {
    "requestId": "019...",
    "nextCursor": "opaque-token"
  }
}
```

List example:

```json
{
  "data": [],
  "meta": {
    "requestId": "019...",
    "nextCursor": "eyJ..."
  }
}
```

Server не обязан возвращать `total`, если cursor count дорогой. UI показывает `hasMore`, а не выдумывает exact total.

## 4. Problem Details

```json
{
  "type": "https://priceweb.local/problems/insufficient-stock",
  "title": "Недостаточно товара",
  "status": 409,
  "detail": "Для позиции SKU-123 доступно 4 единицы.",
  "instance": "/api/v2/orders",
  "code": "INSUFFICIENT_STOCK",
  "requestId": "019...",
  "errors": [
    {
      "field": "items[2].quantity",
      "code": "QUANTITY_EXCEEDS_AVAILABLE",
      "message": "Доступно 4"
    }
  ]
}
```

Обязательные стабильные коды:

- `VALIDATION_ERROR`;
- `AUTHENTICATION_REQUIRED`;
- `INVALID_CREDENTIALS`;
- `PERMISSION_DENIED`;
- `RESOURCE_NOT_FOUND`;
- `ADDRESS_NOT_FOUND`;
- `ADDRESS_DUPLICATE`;
- `ORDER_NOT_FOUND`;
- `PRODUCT_NOT_FOUND`;
- `PRODUCT_UNAVAILABLE`;
- `CART_ITEM_NOT_FOUND`;
- `CART_QUANTITY_OVERFLOW`;
- `CART_SCOPE_MISMATCH`;
- `INSUFFICIENT_STOCK`;
- `INVALID_ORDER_TRANSITION`;
- `DUPLICATE_ORDER_LINES`;
- `IDEMPOTENCY_KEY_REUSED`;
- `STALE_RESOURCE_VERSION`;
- `INVALID_IF_MATCH`;
- `MEMBERSHIP_ALREADY_EXISTS`;
- `LAST_OWNER_PROTECTED`;
- `ORGANIZATION_SELECTION_INVALID`;
- `CONFLICT`;
- `RATE_LIMITED`;
- `ASYNC_JOB_NOT_FOUND`;
- `INTERNAL_ERROR`.

Backend не классифицирует ошибки по русскому тексту exception. UI выбирает локализованный текст по `code`.

## 5. Money

Публичное представление:

```json
{
  "amount": "1234.56",
  "currency": "BYN"
}
```

Правила:

- `amount` — JSON string, не float;
- валюта uppercase ISO 4217;
- scale фиксирован currency/rate profile;
- расчёт выполняется `Decimal`;
- округление выполняется по зафиксированному правилу до записи snapshot;
- order lines хранят amount, currency, unit price и rate snapshots.

Для количеств применяется отдельный тип, чтобы не смешивать quantity, percent и money.

## 6. Sessions

### 6.1 Browser

- login создаёт httpOnly access/refresh cookies и CSRF token;
- mutations требуют `X-CSRF-Token`;
- refresh rotation и reuse detection сохраняются;
- web client не получает refresh token в JSON.

### 6.2 Native

- `clientType=NATIVE` и подтверждённый OAuth-style grant возвращает access + refresh token в JSON;
- refresh token хранится iOS client в Keychain;
- `deviceName`, `os`, `appVersion` записываются в session;
- revoke/reuse detection действует одинаково;
- Bearer refresh не требует browser CSRF.

### 6.3 Auth endpoints

| Method | Path | Назначение |
|---|---|---|
| POST | `/auth/sessions` | Browser/native login grant; `clientType` WEB/NATIVE. |
| POST | `/auth/2fa/challenges/verify` | Завершение 2FA login. |
| POST | `/auth/sessions/refresh` | Ротация session token. |
| DELETE | `/auth/sessions/current` | Logout/revoke current. |
| GET | `/auth/sessions` | Список device sessions. |
| DELETE | `/auth/sessions/{id}` | Revoke one. |
| GET | `/session` | Current user, memberships, active organization. |

`GET /api/v2/session` в текущем expand-срезе возвращает membership-aware контекст: `commercialScope="ORGANIZATION"` и `organizationId` только при явно выбранной active organization; без выбранной organization остаются `commercialScope="USER"`, `organizationId=null` и memberships без фабрикации. Свободный текст `User.company` не выдаётся за organization и сохраняется только под именем `legacyCompany`.

Phase 2 добавляет `Organization`, `OrganizationMembership` и nullable `Order.organization_id` без автоматического backfill. Membership создаётся только явной reviewed operation; одинаковый `User.company` не является основанием для объединения пользователей или заказов. `Order.client_id` остаётся initiator/contact compatibility field. Organization pricing terms не fallback-ятся на legacy user terms внутри organization scope; user-based pricing остаётся fallback только в legacy USER scope.

V2 не кладёт refresh token в access JWT и не использует query token.

## 7. Organizations

### Endpoints

| Method | Path | Назначение |
|---|---|---|
| GET | `/organizations/current` | Активная организация текущего пользователя. |
| GET | `/organizations` | Manager list с server search/sort/cursor. |
| POST | `/organizations` | Создать организацию. |
| GET | `/organizations/{id}` | Детали, legal/delivery summary. |
| PATCH | `/organizations/{id}` | Partial update с `version`. |
| GET | `/organizations/{id}/members` | Membership list. |
| POST | `/organizations/{id}/members` | Добавить существующего `CLIENT` user. |
| PATCH | `/organizations/{id}/members/{userId}` | Роль membership, active state, `version`; требует `If-Match`. |
| PUT | `/session/organization` | Явный выбор активной organization текущего authenticated user; `null` возвращает `USER` scope. |
| GET | `/organizations/{id}/pricing-terms` | Agreement и brand terms. |
| PUT | `/organizations/{id}/pricing-terms` | Полная согласованная замена terms с `version`. |

Client user не выбирает произвольную organization id: backend вычисляет допустимые memberships. Manager operations проверяют RBAC и audit.

Текущий v2 organization slice реализует staff-only `GET /organizations`, `GET /organizations/{id}`,
`GET/POST /organizations/{id}/members` и `PATCH /organizations/{id}/members/{userId}`. Оба list
endpoint используют `CursorResponse`/`CursorMeta`: `limit` по умолчанию равен 50 и ограничен 100,
`total` не возвращается. Поиск выполняется в БД (`legal_name`, `display_name`, `tax_id` для
организаций; `email`, `full_name` для участников). Сортировка ограничена значениями
`legalName|-legalName|createdAt|-createdAt` для organizations и
`fullName|-fullName|email|-email|createdAt|-createdAt` для members.

Курсор — подписанный opaque keyset token с resource, sort и filter signature, а также стабильным
UUID tie-breaker. Невалидный, изменённый или использованный с другим resource/sort/filter курсор
возвращает Problem Details `VALIDATION_ERROR`. List queries используют `LIMIT limit + 1` и не
выполняют Python-фильтрацию или полную загрузку. Membership
создаётся только для уже существующего `CLIENT`; manager/admin не являются commercial members. PATCH
использует `If-Match` (`3` или `W/\"3\"`), atomic version semantics и запрещает оставить организацию без
активного `OWNER`. Деактивация membership очищает `active_organization_id` только у соответствующего user.
Публичные DTO содержат UUID, camelCase, `version` и timestamps, но не содержат `password_hash`,
`fixed_rate` или другие внутренние pricing/credential поля.

### Address book (`/me/organization/addresses`)

Адресная книга доставки организации (Этап 2 дорожной карты). Таблица `organization_addresses`
существует с миграции 0013; уникальность `(organization_id, kind, address_line)` гарантирует БД.

| Method | Path | Назначение |
|---|---|---|
| GET | `/me/organization/addresses` | Адреса активной organization текущего пользователя. |
| POST | `/me/organization/addresses` | Создать адрес; обязателен `Idempotency-Key`. |
| PATCH | `/me/organization/addresses/{addressId}` | Частичное обновление адреса. |
| DELETE | `/me/organization/addresses/{addressId}` | Удалить адрес (204). |

Правила:

- scope вычисляется только через `OrganizationContextService.resolve(user)`: чтение — любой
  активный участник (OWNER/BUYER/CONTACT/VIEWER); без активной organization `GET` возвращает
  `data: []`, `POST` — `409 NO_ORGANIZATION`, PATCH/DELETE — `404 ADDRESS_NOT_FOUND`;
- записывают только OWNER/BUYER; CONTACT/VIEWER на POST/PATCH/DELETE получают
  `403 ADDRESS_FORBIDDEN`;
- `POST` требует заголовок `Idempotency-Key` (1..255 видимых символов, иначе 422
  `VALIDATION_ERROR`). Идемпотентность повторов даёт natural key без отдельного
  key→result-хранилища: повтор с тем же `(kind, addressLine)` в той же организации
  возвращает уже существующий адрес с `201`. Жёсткая гарантия от дублей — unique
  constraint БД `(organization_id, kind, address_line)` (миграция 0013);
- `409 ADDRESS_DUPLICATE` возникает на `PATCH` — при смене `kind`/`addressLine` на пару,
  уже занятую другим адресом организации;
- поля DTO: `id`, `kind` (`LEGAL|DELIVERY|PICKUP`, default `DELIVERY`), `label` (≤120),
  `recipientName` (≤255), `phone` (≤50), `addressLine` (1..500, обязательный), `city` (≤120),
  `postalCode` (≤32), `countryCode` (2 символа, default `BY`), `isDefault`, `createdAt`;
- `PATCH` принимает те же поля опционально; absent — оставляет прежнее значение, явный
  `null` у `label`/`recipientName`/`phone`/`city`/`postalCode` — очищает поле; `null` у
  `kind`/`addressLine`/`countryCode` — `422 VALIDATION_ERROR`; ответ —
  `SuccessResponse[OrganizationAddressOut]`;
- чужой (не из активной organization) или несуществующий адрес → `404 ADDRESS_NOT_FOUND`
  (PATCH/DELETE);
- `isDefault` уникален в рамках `kind`: установка `isDefault: true` транзакционно снимает
  default у остальных адресов того же `kind`;
- `DELETE` возвращает `204` без тела. Заказы не ломаются: `orders.delivery_address_id` —
  opaque UUID без FK-констрейнта (миграция 0015), а человекочитаемый снапшот уже сохранён
  в `orders.delivery_address`.

## 8. Catalog

| Method | Path | Назначение |
|---|---|---|
| GET | `/catalog/products` | Auth product list с cursor, q, brands, series, stock, sort. |
| GET | `/catalog/products/{productId}` | Product by UUID. |
| GET | `/catalog/products/by-sku/{sku}` | Resolve/read by visible SKU. |
| GET | `/catalog/facets` | Server facets с counts/selected state. |
| POST | `/catalog/bulk-resolve` | SKU lines → product ids + validation. |
| POST | `/catalog/exports` | Catalog export job. |

Текущий read-only slice реализует list/detail/by-sku/facets с `CursorResponse`, `Money`, `Rate` и media-resource projection (§9). Цены рассчитываются в том же validated commercial scope, что и cart: USER pricing используется только без активной organization, organization agreement/fixed rate/brand terms — внутри organization scope. Cursor привязан к actor, organization scope и filter signature. Facets пока возвращают доступные brand/series/stock/model values без counts/selected state. Bulk resolve и exports ещё не входят в v2.

Supported sort values задаются enum/OpenAPI, не произвольными строками. Неизвестный sort → `VALIDATION_ERROR`.

Публичная product projection либо не содержит цен/остатков, либо требует auth. Public brand aggregate не делает N+1 series/product calls.

## 9. Media

```json
{
  "id": "uuid",
  "url": "/api/v2/media/2b0f...-uuid",
  "width": 400,
  "height": 400,
  "mimeType": "image/webp"
}
```

S3 key хранится только server-side. `url` — стабильный v2-путь, а не presigned:
`GET /api/v2/media/{mediaId}` отвечает 200 байтами изображения и никогда не
редиректит на внешний S3. Ключом кеша изображений служит `id`; `url` тоже постоянен,
поэтому годится и как ключ кеша. Отсутствующий объект → 404, недоступное хранилище → 502.
Полное описание ресурса и перечень снятых полей — `NATIVE_API_CONTRACT.md` §6.1.

## 10. Cart и favorites

Cart — server resource с явным commercial scope. У одного пользователя есть одна legacy USER cart (`organization_id = null`) и независимая cart для каждой organization, identified by `(user_id, organization_id)`. V1 продолжает читать и изменять только legacy USER cart; v2 выбирает scope через validated `OrganizationContextService`, поэтому клиент не передаёт произвольный `organizationId` в mutation body.

| Method | Path | Назначение |
|---|---|---|
| GET | `/cart` | Текущая scoped cart, актуальные цены и `ETag`. |
| POST | `/cart/items` | Увеличить quantity существующей line или создать её. |
| PUT | `/cart/items/{productId}` | Полностью заменить quantity и note существующей line. |
| DELETE | `/cart/items/{productId}` | Удалить line. |
| DELETE | `/cart` | Очистить текущую scoped cart. |

Все cart mutations требуют `If-Match: "<version>"`; успешный ответ возвращает новую версию в `ETag: "<version>"`. Scoped cart блокируется строкой PostgreSQL, expected version проверяется до изменения, а version увеличивается ровно один раз после успешной мутации. Повтор устаревшего mutation возвращает `409 STALE_RESOURCE_VERSION`; `Idempotency-Key` для cart mutations не используется, поскольку optimistic version не допускает повторного применения того же изменения.

`POST /cart/items` инкрементирует существующую line. `PUT /cart/items/{productId}` заменяет quantity и note; `note: null` явно очищает note, тогда как v1 partial update сохраняет прежний note. Quantity — canonical positive decimal integer string (`"2"`, не `"02"`, `"2.0"` или число `2`) в диапазоне PostgreSQL integer. Cart mutation не резервирует stock: availability остаётся проверкой order create. Неизвестный product возвращает `PRODUCT_NOT_FOUND`, archived/unavailable — `PRODUCT_UNAVAILABLE`.

Cart DTO — `SuccessResponse[CartSummary]`: UUID, nullable `organizationId`, `version`, `items`, `total`, `totalItems` и `exchangeRate`. `totalItems` — число cart lines, а не сумма quantity. Каждое чтение пересчитывает current prices; пустая cart получает currency и rate из active commercial scope. Organization cart использует organization agreement currency, fixed rate при наличии и organization-brand terms; отсутствие brand terms не вызывает fallback на legacy user discounts. Внутренние `photoKey`, S3 keys и другие storage identifiers не выдаются.

Favorites остаются отдельным resources и в текущий v2 slice не реализованы; будущий bulk-add может принимать SKU input, но response обязан содержать resolved product UUID.

## 11. Order create

Endpoint: `POST /api/v2/orders`.

Headers:

```text
Idempotency-Key: <uuid-or-approved-key>
If-Match: <draft version/etag when applicable>
```

Body:

```json
{
  "draftId": "uuid-or-null",
  "items": [
    { "productId": "uuid", "quantity": "6" }
  ],
  "delivery": {
    "method": "PICKUP|DELIVERY",
    "addressId": "uuid-or-null",
    "contactName": "Иван",
    "phone": "+375...",
    "preferredDate": "2026-10-02",
    "comment": "После 14:00"
  }
}
```

Правила:

- product UUID должен принадлежать текущему organization pricing scope;
- duplicate productId запрещён; bulk resolver также агрегирует duplicate SKU до создания строк;
- quantity нормализуется один раз;
- availability проверяется на create;
- availability повторно проверяется при manager confirmation/advance;
- stock автоматически не резервируется;
- price/rate/agreement version фиксируются в snapshots;
- тот же idempotency key + та же fingerprint возвращает исходный order;
- тот же key + другая fingerprint → `IDEMPOTENCY_KEY_REUSED`;
- `delivery.addressId` при `method=DELIVERY` должен ссылаться на адрес активной organization
  адресной книги (§7 Address book): принадлежность проверяется на create, order сохраняет
  `addressId` и человекочитаемый снапшот `delivery.address` = `label, addressLine, city`
  (пустые части пропускаются, обрезка до 500 символов). Неизвестный/чужой addressId → `404
  ADDRESS_NOT_FOUND`; `DELIVERY` без `addressId` сохраняет прежнее поведение
  (`address = null`);
- storage idempotency key остаётся actor-bound: текущая v1 unique схема `(user_id, idempotency_key)` не изменяется; поэтому повтор того же ключа в другой organization scope для того же пользователя возвращает `IDEMPOTENCY_KEY_REUSED`, а не создаёт новый order.

Реализованный create slice добавляет `POST /api/v2/orders` с обязательным `Idempotency-Key`. Успешное создание и replay возвращают `201 Created`; replay помечается `X-Idempotency-Replayed: true`. Fingerprint включает canonical payload, endpoint, authenticated user и resolved `organization_id`. Ответ — `SuccessResponse[OrderDetail]` с UUID `productId`, snapshot цены/курса, `Money`/`Rate`, `organizationId`, `initiatedByUserId` и structured delivery (`addressId` сохраняется как nullable UUID). Internal media/S3 keys не возвращаются. Product rows и цены разрешаются batch-запросами; stock проверяется под row lock без уменьшения или reservation. После успешного v2 create очищается только active scoped cart; v1 create очищает только legacy USER cart.

Fingerprint включает canonicalized payload, organization, authenticated user и target endpoint. Raw JSON bytes не используются, так как key order/whitespace не должны менять semantics.

Fingerprint включает canonicalized payload, organization, authenticated user и target endpoint. Raw JSON bytes не используются, так как key order/whitespace не должны менять semantics.

## 12. Orders

| Method | Path | Назначение |
|---|---|---|
| GET | `/orders` | Organization/client list, cursor, search, status/date filters. |
| POST | `/orders` | Create from current cart/draft. |
| GET | `/orders/{orderId}` | Detail + lines + events. |
| POST | `/orders/{orderId}/cancel` | FSM-safe cancel. |
| POST | `/orders/{orderId}/repeat` | Create new draft with current prices. |
| POST | `/orders/{orderId}/pdf` | Create PDF job. |

Manager transitions используют UUID, `If-Match`/version и stable transition codes. Устаревшая версия → `STALE_RESOURCE_VERSION`.

Текущий v2 order slice реализует `POST /api/v2/orders`, `GET /api/v2/orders` для authenticated client и
`GET /api/v2/orders/{orderId}`. Collection принимает explicit `status` из
`OrderStatus`, `limit` (default 50, максимум 100), opaque signed `cursor` и
необязательные фильтры поиска `q`, `date_from`, `date_to`, `min_total`, `max_total`
(см. ниже); `total` не считается. Сортировка фиксирована как `createdAt,id` (оба значения DESC) и meta всегда
возвращает `requestId`, `hasMore`, `nextCursor`, `limit` и `sort`. Cursor подписан и связан
с actor, выбранной organization scope, status и набором фильтров; недействительный, изменённый или cursor
из другого контекста возвращает `VALIDATION_ERROR` в `application/problem+json`.

Фильтры коллекции (Этап 1 дорожной карты): `q`, `date_from`, `date_to`, `min_total`,
`max_total` — все необязательные и комбинируются через AND с scope и `status`. `q` (до 255 символов) —
регистронезависимый substring-поиск (ILIKE; спецсимволы LIKE `\`, `%`, `_` экранируются,
ввод ищется буквально) по номеру заявки (`seq` как текст), комментарию заявки (`notes`)
и SKU/названию позиций (коррелированный EXISTS по `order_items.product_snapshot`; join
не используется, чтобы не размножать строки keyset-пагинации). `date_from`/`date_to` —
календарные дни (`YYYY-MM-DD`) по `createdAt`, обе границы включительно; `date_to`
покрывает весь день (границы суток — UTC). `min_total`/`max_total` — включительно по
сумме заявки (`total`). Фильтры не меняют состав `OrderSummary` и не включают `total`
в meta; при пустом результате возвращается `data: []` с `hasMore: false` и
`nextCursor: null`.

Create принимает `items[].productId`, `quantity` и optional `note`, запрещает duplicate
`productId` на validation layer, разрешает products одним batch lookup и применяет pricing
выбранной organization. Неизвестный product возвращает `PRODUCT_NOT_FOUND`, archived/
unavailable — `PRODUCT_UNAVAILABLE`, а превышение stock — `INSUFFICIENT_STOCK` с HTTP 409.
`delivery.addressId` валидируется по адресной книге активной organization после проверки
позиций: чужой/несуществующий адрес → `404 ADDRESS_NOT_FOUND`, валидный адрес фиксируется
в order как `addressId` + текстовый снапшот `label, addressLine, city`.
Все ошибки имеют Problem Details code и `requestId`. Созданный order и replay имеют HTTP 201;
replay возвращает исходный `OrderDetail` и `X-Idempotency-Replayed: true`. Structured
delivery сохраняется в order snapshot, включая nullable `addressId`; stock не резервируется
и не уменьшается.

`POST /api/v2/orders/{orderId}/cancel` возвращает `SuccessResponse[OrderDetail]`. Клиент
может отменить только заявку в статусе `NEW` или `IN_PROGRESS`; для `SHIPPED`, `COMPLETED`
и `CANCELLED` возвращается HTTP 409 с кодом `ORDER_NOT_CANCELABLE`. Доступ к заявке
проверяется до изменения состояния, а organization order остаётся недоступным outsider.

`POST /api/v2/orders/{orderId}/repeat` требует `If-Match` текущей scoped cart, возвращает
`SuccessResponse[CartSummary]` и устанавливает `ETag` новой версии. Повтор добавляет current
products из исходной заявки в active cart с агрегацией quantity и актуальными ценами.
Недоступные или архивные позиции пропускаются с сохранением существующей v1 silent-skip
semantics; version увеличивается один раз только если cart изменилась. Если исходная заявка
принадлежит organization, активной должна быть именно эта organization, иначе backend
возвращает `CART_SCOPE_MISMATCH`: перенос в другую organization не выполняется скрыто. Для
legacy order v2 использует active commercial context, а v1 без scope сохраняет legacy USER cart и user pricing.

Collection DTO — отдельный `OrderSummary`: `id`, `sequence`, `organizationId`,
`initiatedByUserId`, `status`, `total` (`Money`), `exchangeRate` (`Rate`), `createdAt`,
`updatedAt`, `version`. Он не содержит order lines/items, media/S3 keys или presentation
поля клиента. Scope вычисляется только через `OrganizationContextService.resolve(user)`:
при активной organization видны organization orders и legacy/NULL-organization orders,
инициированные текущим пользователем; без выбранной organization — только legacy/NULL
orders текущего пользователя. Outsider не видит organization orders.

## 13. Notifications and jobs

| Method | Path | Назначение |
|---|---|---|
| GET | `/notifications` | Feed + unread count, cursor. |
| POST | `/notifications/{id}/read` | Read one. |
| POST | `/notifications/read-all` | Read all visible. |
| GET | `/notifications/stream` | SSE/polling-compatible event feed. |
| GET | `/jobs/{jobId}` | Common async job. |
| POST | `/jobs/{jobId}/cancellation` | Best-effort cancellation when supported. |

SSE event содержит `eventId`, `type`, `occurredAt` и resource payload. Reconnect использует `Last-Event-ID`; после reconnect client делает feed refresh для reconciliation.

## 14. Files

- metadata list/detail содержит file resource, display name, type, size, dates, access;
- download — short-lived URL endpoint/resource;
- manager upload/delete использует file UUID и `If-Match` там, где применимо;
- internal object key не выдаётся;
- content type, magic bytes, size и access проверяются server-side.

## 15. Manager/admin

Manager v2 resources:

- organizations, contacts, memberships, pricing terms;
- products, stock/pricing overrides;
- brands and series aggregates;
- orders/status transitions;
- imports, price versions, rollback;
- currencies;
- files and media;
- audit;
- admin roles/broadcast notifications.

Все большие списки используют server-side q/sort/cursor. Presentation-shaped `/dashboard` заменяется composable domain queries или thin metric endpoints без quick actions и formatted UI blocks.

## 16. Concurrency

- изменяемые resources имеют integer `version` или строгий ETag;
- create/patch/delete, меняющие состояние, принимают `If-Match` или expected version;
- atomic SQL update/row lock проверяет current version;
- mismatch → 409 `STALE_RESOURCE_VERSION`;
- cart mutations и organization-order repeat возвращают текущую/новую cart version в `ETag`;
- response не скрывает текущую версию;
- retries после timeout допустимы только при известной idempotency semantics: order create использует `Idempotency-Key`, cart mutations — `If-Match` без отдельного idempotency key.

## 17. OpenAPI и compatibility gates

- OpenAPI генерируется из v2 routers и schemas;
- текущий v2-only snapshot: `apps/api/tests/fixtures/openapi/api-v2.openapi.json`;
- snapshot воспроизводится командой `python -m app.scripts.export_v2_contract` из `apps/api`;
- `apps/api/tests/test_contract_artifacts.py` сверяет snapshot с `app.openapi()` и не включает v1 paths в v2 diff;
- все v2 operations объявляют Problem Details как `application/problem+json` через единый `problem_responses()` helper;
- shared JSON fixtures: `apps/api/tests/fixtures/v2/*.json` (Money, Rate, order/session/catalog/cart success envelopes, mutation requests, Problem Details);
- frontend mapper использует эти wire fixtures через `apps/web/test/fixtures/problem-details-mapper.json`; Vitest проверяет v2, v1, nested и fallback cases;
- semantic compatibility gate запускает `python -m app.scripts.check_v2_semantics BASE CURRENT` и проверяет удаление path/method, narrowing enum, новые required parameters и удаление success responses;
- legacy migration fixture: `apps/api/tests/fixtures/legacy/price_web_legacy_v1.json`;
- breaking change завершает build;
- DTO fixtures используются frontend contract tests и позднее iOS Codable fixtures;
- ручные page-local interfaces не являются источником контракта.

## 18. Миграционные проверки

До cutover:

- v1 regression suite зелёный;
- v2 happy/auth/permission/money/media/idempotency/concurrency tests зелёный;
- organization isolation tests зелёные;
- USER/ORGANIZATION carts существуют раздельно, а migration downgrade отказывается удалять organization carts;
- clean Alembic chain содержит `ADMIN`;
- historical order sequence backfill проверен;
- public projections не содержат private pricing;
- media response не содержит storage key;
- float отсутствует в публичных v2 money schemas;
- Problem Details не зависит от localized exception text.
