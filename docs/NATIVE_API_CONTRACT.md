# Native API Contract (iOS + Android)

> Рабочий контракт нативных клиентов: iOS (SwiftUI) и Android (Compose) поверх общего
> Kotlin Multiplatform-ядра. Начало нативной разработки разрешено после стабилизации
> web/API v2 и публикации проверенного OpenAPI snapshot.

## 1. Цель

Нативные приложения используют тот же API v2 и organization-aware data model, что и replacement web. Они не получают отдельную копию цен, заказов, stock rules или статусов.

Оба приложения равны по функциям, но не по оболочке: iOS — SwiftUI, Android — Compose. Общими остаются контракт и транспортный слой (§15). Расхождение функций между платформами — дефект, а не допустимое упрощение.

Нативное приложение отвечает за:

- нативную навигацию и формы;
- защищённое хранение сессии (Keychain на iOS, EncryptedSharedPreferences на Android);
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

Если любой пункт не выполнен, нативный клиент может разрабатываться против mock repository, но не против нестабильного production API.

## 3. Client transport

- base URL: environment-specific absolute HTTPS URL; in web deployments допускается same-origin proxy, но native target не полагается на browser cookies;
- HTTP-клиент общего ядра — Ktor; iOS использует его поверх `URLSession`, Android — поверх OkHttp; JSON codec одинаков;
- Bearer access token в memory;
- refresh token в защищённом хранилище платформы (Keychain на iOS, EncryptedSharedPreferences на Android), access group соответствует bundle/team policy;
- refresh token никогда не пишется в UserDefaults/SharedPreferences без шифрования, logs или analytics;
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

1. прочитать refresh token из защищённого хранилища платформы;
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

Фактическая проекция `GET /api/v2/catalog/products/{productId}` и элемента списка:

```json
{
  "id": "uuid",
  "sku": "LED-12-E27-3000",
  "name": "Лампа LED E27 12W",
  "brand": { "id": "uuid", "name": "OSRAM" },
  "series": { "id": "uuid", "name": "Classic", "brandId": "uuid" },
  "stockStatus": "IN_STOCK|PREORDER",
  "stockQuantity": 120,
  "attributes": {},
  "basePrice": { "amount": "1.05", "currency": "BYN" },
  "retailPrice": { "amount": "0.82", "currency": "BYN" },
  "clientPrice": { "amount": "0.70", "currency": "BYN" },
  "exchangeRate": { "value": "3.0000", "scale": 4, "source": "NBRB" },
  "hasDiscount": true,
  "thumbnail": null,
  "media": []
}
```

Расхождения с прежней редакцией контракта, снятые 2026-09-27:

- `unit` отсутствует — в модели `Product` такой колонки нет, единица измерения единична и не входит в товарный справочник;
- `brand.slug` / `series.slug` отсутствуют — slug вычисляется только для публичной SEO-витрины (§16 п.29), в v2 не публикуется;
- `availability{status,quantity}` заменён плоскими `stockStatus` + `stockQuantity`; допустимых значений два, `ARCHIVED` отфильтровывается сервером на уровне выборки;
- `version` отсутствует — optimistic concurrency в v2 живёт на cart/order, у каталожных товаров нет изменяемой версии;
- поля `price` не существует: цена разнесена на `basePrice` (всегда BYN), `retailPrice` и `clientPrice` (в display-валюте клиента) плюс `exchangeRate`.

Правила чтения цен:

- `retailPrice` и `clientPrice` сравнимы только внутри одной `currency` — это display-валюта пользователя или pricing agreement организации;
- дельта между ними считается в BYN, валюта дельты — валюта `basePrice`;
- `hasDiscount` управляет тем, какую из двух цен показывает UI как основную (в web — тумблер «Розница / Со скидкой», в нативном клиенте — такой же переключатель);
- `priceCalcMode` (`fixed` | `nbrb_current`) — выбор между договорным и текущим курсом НБ РБ; передаётся query-параметром, а не хранится в продукте.

Native client не кэширует personalized price бессрочно. Price имеет organization pricing context и может быть invalidated; UI показывает timestamp/refresh behavior.

## 6.1 Media

Изображения публикуются отдельным ресурсом; S3-ключ никогда не покидает сервер.

```json
{
  "id": "uuid",
  "url": "/api/v2/media/2b0f...-uuid",
  "width": 400,
  "height": 400,
  "mimeType": "image/webp"
}
```

- `id` — стабильный `uuid5` от S3-ключа: одинаковый для всех клиентов. **Ключ кеша изображений — `id`**;
- `url` — стабильный путь v2; `GET /api/v2/media/{mediaId}` отвечает **200 байтами изображения** (Content-Type из реестра), без редиректа на внешний S3. URL тоже постоянен, но `id` переносится между версиями контракта надёжнее. Presigned URL наружу не отдаётся никогда;
- `width`, `height` и `mimeType` следуют конвенции импортёра фото: суффикс `_thumb` → 400×400, large → 1200×1200, формат webp. Те же значения лежат в реестре `media_assets` — он нужен для обратного перехода `id → ключ`, потому что `uuid5` необратим;
- в ответе списка (`/catalog/products`) присутствует только `thumbnail` — один репрезентативный кадр, чтобы не раздувать payload плитки; полный `media[]` отдаёт детальная карточка;
- `thumbnail` — фото самого товара, а если его нет, фото серии; если нет и его, `thumbnail` равен `null` — это штатное состояние, а не ошибка;
- **фактически `thumbnail` сейчас несёт large-кадр.** Загрузчик кладёт в бакет два варианта — `{key}.webp` (1200×1200) и `{key}_thumb.webp` (400×400, §16 п.17), — но в БД пишется только large-ключ, а thumb выводится заменой суффикса. v2 отдаёт ключ из БД, поэтому плитка тянет large (на проде 27.09 это ~36 КБ против ~12 КБ у thumb, на фото товара). Выводить наличие миниатюры из самого `thumbnail` нельзя: отдельного `?size=thumb` в контракте нет.

### Поля, снятые из контракта 2026-09-27

Редакция §6.1 до 2026-09-27 описывала поля, которых нет ни в DTO
(`app/schemas/v2/media.py`), ни в KMP-модели `MediaResource`
(`core/shared`), ни в web-схеме. Они сняты, а не «ещё не реализованы»:

- `kind` (`PRODUCT_IMAGE|SERIES_IMAGE`) — фолбэк на фото серии разрешается на сервере, и клиенту не нужно различать источник кадра;
- `thumbnailUrl` (`?size=thumb`) — снят вместе с `kind`: отдельного параметра размера в контракте нет, а `thumbnail` сейчас несёт large-кадр (см. выше), так что параметр был бы единственным способом получить миниатюру; решение об этом — открытое;
- `alt` — подписью кадра служит название товара, которое клиент и так получает в `name`;
- `sortOrder` — порядок `media[]` это порядок хранения галереи, отдельное поле не нужно.

Возвращать любое из них можно только вместе с правкой DTO, KMP-модели и
`apps/web/domain/api/v2/catalog.schema.ts`: web-схема строгая (`.strict()`) и
отвергнет ответ с лишним полем, а нативный клиент его не декодирует.

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

### Address book (checkout delivery)

Адресная книга доставки активной organization; нативному клиенту нужна на шаге checkout.
Полные правила — `API_V2_CONTRACT.md` §7 «Address book».

| Method | Path | Назначение |
|---|---|---|
| GET | `/me/organization/addresses` | Список адресов (любой активный участник; без organization — пустой список). |
| POST | `/me/organization/addresses` | Создать адрес; заголовок `Idempotency-Key` обязателен; только OWNER/BUYER. |
| PATCH | `/me/organization/addresses/{addressId}` | Частичное обновление; только OWNER/BUYER. |
| DELETE | `/me/organization/addresses/{addressId}` | Удалить (204); только OWNER/BUYER. |

DTO — `OrganizationAddressOut`: `id`, `kind` (`LEGAL|DELIVERY|PICKUP`), `label`,
`recipientName`, `phone`, `addressLine`, `city`, `postalCode`, `countryCode`, `isDefault`,
`createdAt` (camelCase). Стабильные коды ошибок: `ADDRESS_DUPLICATE` (409, дубль
org+kind+addressLine при PATCH), `ADDRESS_NOT_FOUND` (404, чужой/несуществующий),
`ADDRESS_FORBIDDEN` (403, роль без права записи), `NO_ORGANIZATION` (409, POST без
активной organization). Повтор `POST` с тем же `(kind, addressLine)` идемпотентно
возвращает существующий адрес с `201` (natural key + unique constraint БД). `isDefault`
единственен в рамках `kind` — сервер сам снимает прошлый default. PATCH: absent сохраняет
прежнее значение, явный `null` у nullable-полей очищает. В `POST /orders` передавайте
выбранный адрес как `delivery.addressId`; сервер проверит принадлежность организации и
сохранит снапшот-строку в `delivery.address`.

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

Общий контракт и транспорт живут в Kotlin Multiplatform-ядре; UI остаётся нативным на каждой платформе.

```text
core/                      # KMP: models, DTO, ApiClient, repositories, errors
ios/PriceWebApp/           # SwiftUI composition, app lifecycle
ios/PriceWebCore/          # KMP-обёртки, Keychain, платформенные протоколы
ios/PriceWebFeatures/      # auth, catalog
ios/PriceWebTests/         # decoding, store, auth tests
android/app/               # Compose UI + DI
android/core/              # KMP-обёртки, EncryptedSharedPreferences
```

Правила границ:

- `core` не зависит ни от UI-фреймворков, ни от платформенных API; платформенные зависимости объявляются `expect/actual` (secure storage, файловый кеш);
- `core` не содержит бизнес-решений presentation-слоя — только транспорт, декодирование и репозитории;
- feature-модули зависят от протоколов `core`, а не от конкретных реализаций;
- ни один UI-слой не строит S3-ключи и не знает про presigned URL — только про `mediaId`.

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

Контрактные тесты клиентов декодируют **те же JSON-фикстуры**, что проверяются против pydantic-моделей бэкенда (`apps/api/tests/fixtures/v2/*.json`). Это единственный источник правды для обеих платформ: расхождение фикстуры и DTO ломает сборку тестов, а не всплывает на устройстве.

## 17. Parity с web

Перед release candidate сравниваются:

- один и тот же SKU получает одну organization price;
- наличие и price semantics совпадают;
- cart totals после server validation совпадают;
- повторная отправка не создаёт second order;
- заказ виден в web и в обоих нативных клиентах с одинаковыми lines/snapshots;
- статусы и audit-visible events синхронизированы;
- notifications приводят к одному resource state;
- v1 не нужен для core flow ни на одной из платформ.

Parity между платформами проверяется отдельно: iOS и Android декодируют один и тот же набор фикстур и обязаны давать одинаковые presentation-значения для price, availability и media.
