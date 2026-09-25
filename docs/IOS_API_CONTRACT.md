# iOS API Contract

> Рабочий контракт будущего SwiftUI-клиента. Начало iOS-разработки разрешено после стабилизации web/API v2 и публикации проверенного OpenAPI snapshot.

## 1. Цель

SwiftUI-приложение использует тот же API v2 и organization-aware data model, что и replacement web. Оно не получает отдельную копию цен, заказов, stock rules или статусов.

Нативное приложение отвечает за:

- нативную навигацию и формы;
- Keychain session storage;
- offline/retry UX для уже известных данных;
- локальную presentation state.

Backend остаётся источником истины для price, availability, order ownership, permissions и state transitions.

## 2. Стартовые условия

До первой production implementation должны быть выполнены:

- API v2 OpenAPI snapshot зафиксирован и проходит semantic diff;
- auth grant для native clients реализован и tested;
- refresh rotation/reuse detection работает для Bearer sessions;
- Product, Money, Organization, OrderLine и Order fixtures опубликованы;
- order create/idempotency contract покрыт contract tests;
- server-side search/sort/cursor semantics документированы;
- web parity matrix утверждена.

Если любой пункт не выполнен, iOS может разрабатываться против mock repository, но не против нестабильного production API.

## 3. Client transport

- base URL: environment-specific absolute HTTPS URL; in web deployments допускается same-origin proxy, но native target не полагается на browser cookies;
- `URLSession` с JSON decoder/encoder;
- Bearer access token в memory;
- refresh token в Keychain, access group соответствует bundle/team policy;
- refresh token никогда не пишется в UserDefaults, logs или analytics;
- ATS требует HTTPS, кроме локального development override;
- certificate pinning не входит в первый MVP, если нет отдельного security requirement.

## 4. Auth

### Login

`POST /api/v2/auth/sessions` с `clientType=NATIVE` возвращает:

```json
{
  "data": {
    "accessToken": "jwt",
    "accessTokenExpiresAt": "2026-09-24T14:30:00Z",
    "refreshToken": "opaque-or-jwt",
    "refreshTokenExpiresAt": "2026-09-29T14:30:00Z",
    "session": {
      "id": "uuid",
      "deviceName": " Yaroslav's iPhone",
      "createdAt": "2026-09-24T12:00:00Z"
    }
  }
}
```

2FA challenge не возвращает session tokens до verify.

### Refresh

- access истекает → single-flight refresh;
- несколько параллельных 401 ждут один refresh;
- после refresh один retry каждого запроса;
- refresh failure очищает Keychain session и переводит app в logged-out state;
- reuse detection немедленно завершает session family и требует нового login.

### Session restore

При запуске:

1. прочитать refresh token из Keychain;
2. выполнить refresh;
3. загрузить `/session`;
4. восстановить active organization;
5. только затем показывать authenticated UI.

## 5. Общие models

### Money

```swift
struct Money: Codable, Hashable {
    let amount: Decimal
    let currency: CurrencyCode
}
```

- amount декодируется из decimal string;
- currency — uppercase ISO code;
- formatted output создаётся только presentation layer;
- вычисления не выполняются на Double.

### Date

- date: `yyyy-MM-dd` custom decoding;
- datetime: RFC 3339 ISO8601 с fractional seconds fallback;
- все timestamps трактуются как UTC, display timezone — настройка пользователя/устройства.

### IDs

- все resource identifiers — `UUID`;
- SKU — отдельный поисковый/display string;
- write DTO никогда не использует SKU как path identity.

## 6. Product

```json
{
  "id": "uuid",
  "sku": "LED-12-E27-3000",
  "name": "Лампа LED E27 12W",
  "brand": { "id": "uuid", "name": "OSRAM", "slug": "osram" },
  "series": { "id": "uuid", "name": "Classic", "slug": "classic" },
  "unit": "шт.",
  "price": { "amount": "0.82", "currency": "BYN" },
  "retailPrice": { "amount": "1.05", "currency": "BYN" },
  "availability": {
    "status": "IN_STOCK|ON_ORDER|ARCHIVED",
    "quantity": "120"
  },
  "media": [],
  "attributes": {},
  "version": 4
}
```

Native client не кэширует personalized price бессрочно. Price имеет organization pricing context и может быть invalidated; UI показывает timestamp/refresh behavior.

## 7. Organization and account

`/session` возвращает:

- current user;
- role;
- memberships;
- active organization;
- permissions relevant to client capabilities;
- notification settings summary.

Organization содержит display/legal name, contacts, delivery addresses и pricing agreement reference. Personal legal fields не заменяют organization ownership.

Если у пользователя несколько organizations:

- server v2 определяет active organization;
- client хранит только UUID выбора;
- server проверяет membership при каждой organization-scoped операции;
- смена active organization очищает organization-scoped cart/query caches;
- background refresh никогда не смешивает данные организаций.

## 8. Catalog

- q, brand/series/stock filters и sort сериализуются одинаково с web;
- URL mapping в SwiftUI заменяется `CatalogQuery` value type;
- page navigation использует cursor, не вычисляет offset из количества элементов;
- stale responses отменяются через task cancellation/generation token;
- product detail lookup выполняется по UUID; SKU resolve доступен для ручного ввода.

Offline policy:

- in-memory или disk-cached public-safe catalog может отображаться с timestamp;
- private price/order data не попадает в unprotected shared cache;
- offline submit заявки запрещён, если актуальный server validation/idempotency невозможен.

## 9. Cart

Cart — server-persisted resource с явным commercial scope. У пользователя одна legacy USER cart и независимая cart для каждой organization; native client выбирает только UUID active organization через session API и не передаёт scope в cart body.

- `GET /cart` возвращает `CartSummary` и `ETag`;
- `POST /cart/items` инкрементирует существующую line;
- `PUT /cart/items/{productId}` полностью заменяет quantity/note, причём `note: null` очищает note;
- `DELETE /cart/items/{productId}` удаляет line, `DELETE /cart` очищает scoped cart;
- каждая mutation отправляет `If-Match` с последней известной version и сохраняет новый `ETag` из ответа;
- `STALE_RESOURCE_VERSION` приводит к refetch и явному conflict state, а не silent overwrite;
- `Idempotency-Key` для cart не используется: повторная mutation защищена version;
- quantity декодируется как canonical positive integer, хотя wire representation — decimal string;
- `totalItems` означает число lines, а не сумму quantity;
- server пересчитывает current prices, currency и rate при каждом чтении; organization pricing не заменяется user pricing.

Cart содержит последний известный price projection, но окончательный расчёт перед submit — server-side. При logout, user switch и organization switch in-memory store очищается или перезагружается для нового scope; старый organization cart не смешивается с новым. Cart lines не содержат internal photo/S3 keys.

## 10. Order create

`POST /orders` с `Idempotency-Key`.

Client flow:

1. получить/создать draft;
2. загрузить server-calculated checkout;
3. валидировать delivery локально для UX;
4. создать key и fingerprint candidate в памяти;
5. submit;
6. при network timeout повторять с тем же key;
7. при явном 409 `IDEMPOTENCY_KEY_REUSED` не менять payload автоматически;
8. при success очистить key и показать order detail.

Key создаётся заново при любом содержательном изменении draft/delivery. Он не хранится бессрочно в UserDefaults; незавершённый draft может хранить key только в защищённом local store до явного discard/TTL.

## 11. Order model

```json
{
  "id": "uuid",
  "sequence": "PR-2026-000123",
  "organizationId": "uuid",
  "initiatedByUserId": "uuid",
  "status": "SUBMITTED",
  "currency": "BYN",
  "total": { "amount": "354.00", "currency": "BYN" },
  "lines": [],
  "events": [],
  "createdAt": "2026-09-24T12:00:00Z",
  "updatedAt": "2026-09-24T12:00:00Z",
  "version": 1
}
```

Status registry совпадает с web и OpenAPI. Native client не создаёт локальный переход статуса, которого нет в серверном enum. Display copy может локализоваться, machine code остаётся server value.

## 12. Notifications

- initial feed/unread count через REST;
- push — через поддержанный v2 stream transport либо controlled polling;
- reconnect/resume и reconciliation соответствуют API v2;
- logout закрывает stream и удаляет in-memory state;
- deep link обрабатывается только для resource UUID, полученного от trusted server payload.

## 13. Files and exports

- короткоживущий download URL открывается системным download/share flow;
- native app не строит S3 key URL;
- file metadata и access приходят из `/files`;
- PDF/CSV отображаются системными средствами или Quick Look, основной commerce flow остаётся нативным.

## 14. Offline и ошибки

Problem Details mapping:

- authentication/session errors → login flow;
- permission → no-access screen;
- insufficient stock → позиционная корректировка;
- stale version → refetch + conflict notice;
- invalid transition → disabled action + server explanation;
- rate limit → countdown/retry date;
- network timeout → retry with same idempotency key для create;
- internal error → problem code + requestId в diagnostics.

Не отображать raw exception или stack trace пользователю. В crash/analytics telemetry разрешены code, status, endpoint class и requestId, но не auth headers, tokens или полные private payloads.

## 15. Модули приложения

Рекомендуемая структура после старта:

```text
ios/PriceWebApp/          # SwiftUI composition, app lifecycle
ios/PriceWebCore/         # models, API contracts, repositories, errors
ios/PriceWebFeatures/     # auth, catalog, cart, orders, account
ios/PriceWebTests/        # contract, decoding, reducer/store, auth tests
```

`PriceWebCore` не зависит от SwiftUI. Feature modules зависят от core protocols. APIClient не импортирует конкретные feature stores.

## 16. Test matrix

- login, 2FA, restore, logout;
- refresh single-flight и retry;
- refresh reuse/revocation;
- organization switch cache cleanup;
- decimal/currency/date decoding;
- catalog cursor and cancellation;
- cart conflict;
- USER/ORGANIZATION cart switch;
- idempotent order create after timeout;
- repeat order with active-scope mismatch;
- status decoding and timeline;
- Problem Details mapping;
- offline catalog display and blocked submit;
- VoiceOver labels/hints;
- Dynamic Type без обрезанных actions;
- safe area and keyboard avoidance;
- light/dark token parity.

## 17. Parity с web

Перед release candidate сравниваются:

- один и тот же SKU получает одну organization price;
- наличие и price semantics совпадают;
- cart totals после server validation совпадают;
- повторная отправка не создаёт second order;
- заказ виден web и iOS с одинаковыми lines/snapshots;
- статусы и audit-visible events синхронизированы;
- notifications приводят к одному resource state;
- v1 не нужен для core iOS flow.
