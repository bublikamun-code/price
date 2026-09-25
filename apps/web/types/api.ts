// Типы API-контрактов. См. ARCHITECTURE_PLAN.md §6, app/schemas/.
// Auth — плоский ответ; catalog — конверт {data, meta}.

export type UserRole = 'CLIENT' | 'MANAGER' | 'ADMIN'
export type StockStatus = 'IN_STOCK' | 'PREORDER' | 'ARCHIVED'

export interface ProblemFieldError {
  field: string
  code: string
  message: string
}

export interface ProblemDetails {
  type: string
  title: string
  status: number
  detail: string
  instance: string
  code: string
  requestId: string
  errors: ProblemFieldError[]
}

export interface MappedApiError {
  status?: number
  type?: string
  title?: string
  detail?: string
  instance?: string
  code?: string
  requestId?: string
  errors: ProblemFieldError[]
  message: string
  isProblemDetails: boolean
}

export interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
  // Принудительная смена пароля при первом входе (бэкенд может не отдавать — фича WIP).
  force_password_change?: boolean
}

export interface UserPublic {
  id: string
  email: string
  full_name: string
  company: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  display_currency: string
  consent_accepted: boolean
  // 2FA менеджера (фича H, §16 п.22): наличие TOTP-секрета на бэкенде.
  totp_enabled: boolean
  // Дайджест изменения цен (in-app уведомления). См. PATCH /api/v1/auth/me.
  price_digest_enabled: boolean
  price_digest_sources: string[] // только 'cart' | 'favorite' | 'orders'
  // Дополнительные поля из .output.bak (могут отсутствовать в старом бэкенде)
  discount_percent?: number
  manager?: { full_name: string } | null
  // Принудительная смена пароля при первом входе (WIP на бэкенде).
  force_password_change?: boolean
}

// ---------- 2FA (фича H, §16 п.22) ----------

// POST /auth/login при включённой 2FA: 200 {"data": {two_fa_required, ticket}} — без токенов и кук.
export interface TwoFALoginRequired {
  two_fa_required: true
  ticket: string
  // Может прийти вместе с ticket: после verify2fa тоже потребуется смена пароля.
  force_password_change?: boolean
}

export interface TwoFALoginEnvelope {
  data: TwoFALoginRequired
}

// POST /auth/2fa/setup → {"data": {secret, otpauth_uri, qr_png_data_url}}.
export interface TwoFASetupOut {
  secret: string
  otpauth_uri: string
  qr_png_data_url: string
}

export interface TwoFASetupResponse {
  data: TwoFASetupOut
}

// POST /auth/2fa/enable → {"data": {recovery_codes: [8 строк]}} (показ ровно 1 раз).
export interface TwoFAEnableResponse {
  data: { recovery_codes: string[] }
}

// ---------- Журнал сессий (фича I, §16 п.22) ----------

export interface SessionOut {
  id: string
  user_agent: string | null
  ip: string | null
  created_at: string
  expires_at: string
  current: boolean
}

export interface SessionListResponse {
  data: SessionOut[]
}

export interface BrandRef {
  id: string
  name: string
}

export interface SeriesRef {
  id: string
  name: string
  brand_id?: string | null
  photo_key?: string | null
}

export interface ProductCard {
  id: string
  sku: string
  name: string
  brand: BrandRef | null
  series: SeriesRef | null
  stock_status: StockStatus
  photo_key: string | null
  attributes: Record<string, unknown>
  base_price_byn: number
  retail_price: number
  client_price: number
  currency: string
  rate_source: string
  has_discount: boolean
  // Точный остаток в шт (null — не раскрывается). Используется для ограничения qty.
  stock_qty?: number | null
}

export interface ProductDetail extends ProductCard {
  override_price: number | null
  /** S3-ключи дополнительных фото (основное photo_key не входит) — галерея в карточке товара. */
  photos?: string[]
}

export interface MetaPage {
  page: number
  per_page: number
  total: number
}

export interface CatalogPage {
  data: ProductCard[]
  meta: MetaPage
}

export interface FiltersOut {
  brands: BrandRef[]
  series: SeriesRef[]
  stock: string[]
  models?: string[]
}

// Экспорт каталога (CSV/XLSX/PDF). См. §6 + app/api/v1/catalog.py, §16 п.16, п.25.
export type ExportFormat = 'csv' | 'xlsx' | 'pdf'
export type ExportJobStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'

export interface ExportStartOut {
  job_id: string
}

export interface ExportJobOut {
  job_id: string
  status: ExportJobStatus
  format: ExportFormat
  error?: string | null
  url?: string | null // presigned-ссылка (5 мин), только при DONE
}

// Импорт прайс-листа (менеджер). См. §6 + app/api/v1/manager/prices.py.
export type ImportMode = 'UPSERT' | 'REPLACE' | 'ARCHIVE_MISSING'
export type PriceListVersionStatus = 'QUEUED' | 'PROCESSING' | 'DONE' | 'FAILED'

export interface ImportUploadOut {
  version_id: string
  status: PriceListVersionStatus
  filename: string
  created_at: string
}

export interface PriceListVersionRead {
  id: string
  filename: string
  import_mode: ImportMode
  status: PriceListVersionStatus
  rows_total: number
  rows_ok: number
  rows_error: number
  base_currency: string
  rate_to_byn: number
  rate_source: string | null
  error_log_key: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  uploaded_by: string | null
  // Аудит отката версии (§16 п.14): заполнено — версия уже откачена.
  rolled_back_at?: string | null
  rolled_back_by?: string | null
}

export interface PriceListVersionPage {
  data: PriceListVersionRead[]
  meta: MetaPage
}

// Ответ отката версии прайса (§16 п.14): восстановленные и архивированные товары.
export interface RollbackOut {
  version: PriceListVersionRead
  restored: number
  archived: number
}

// Photo-ZIP: обработка ZIP с фото серий. См. §6 + app/api/v1/manager/prices.py, §16 п.17.
export interface PhotoZipStartOut {
  job_id: string
}

export interface PhotoZipJobOut {
  job_id: string
  status: ExportJobStatus
  files: number       // обработано изображений
  matched: number     // привязано к сериям
  unmatched: number   // без серии (фото всё равно залиты)
  error?: string | null
  errors: string[]    // первые 50 ошибок по файлам
  created_at?: string | null
}

// История цены товара.
export interface PriceHistoryItem {
  base_price: number
  override_price: number | null
  changed_at: string
}

// ---------- Этап 6: Заявки / Корзина / Избранное ----------

export type OrderStatus = 'NEW' | 'IN_PROGRESS' | 'SHIPPED' | 'COMPLETED' | 'CANCELLED'

export interface OrderItemCreate {
  sku: string
  quantity: number
  note?: string | null
}

export interface OrderCreate {
  items: OrderItemCreate[]
  notes?: string | null
  price_calc_mode?: 'fixed' | 'nbrb_current'
}

export interface OrderStatusUpdate {
  status: OrderStatus
  manager_id?: string | null
}

export interface OrderItemRead {
  id: string
  product_id: string | null
  product_snapshot: Record<string, unknown>
  quantity: number
  unit_price: number
  currency_code: string
  note: string | null
}

export interface OrderRead {
  id: string
  seq?: number | null
  client_id: string
  client_name?: string | null
  client_company?: string | null
  manager_id: string | null
  status: OrderStatus
  currency_code: string
  exchange_rate: number
  rate_source: string | null
  total_amount: number
  notes: string | null
  created_at: string
  updated_at: string
  items?: OrderItemRead[] | null
}

export interface OrderListPage {
  data: OrderRead[]
  meta: MetaPage
}

export interface CartItemCreate {
  sku: string
  quantity: number
  note?: string | null
}

export interface CartItemUpdate {
  quantity?: number | null
  note?: string | null
}

export interface CartItemRead {
  product_id: string
  sku: string
  name: string
  brand_name: string | null
  photo_key: string | null
  stock_status: StockStatus
  quantity: number
  note: string | null
  unit_price: number
  currency: string
  line_total: number
}

export interface CartRead {
  id: string
  items: CartItemRead[]
  total_amount: number
  total_items: number
}

export interface FavoriteCreate {
  sku: string
}

export interface FavoriteRead {
  product_id: string
  sku: string
  name: string
  brand_name: string | null
  photo_key: string | null
  stock_status: StockStatus
  base_price_byn: number
  retail_price: number
  client_price: number
  currency: string
  has_discount: boolean
}

export interface FavoriteListPage {
  data: FavoriteRead[]
  meta: MetaPage
}

// ---------- Уведомления (in-app центр, SITEMAP `/notifications`) ----------

export type NotificationType =
  | 'NEW_ORDER'
  | 'ORDER_STATUS_CHANGED'
  | 'PRICE_CHANGED'
  | 'PRICE_CHANGED_DIGEST'
  | 'STOCK_CHANGED'
  | 'IMPORT_FAILED'
  | 'RATE_FETCH_FAILED'
  | 'ACCOUNT_CREATED'

export interface NotificationItem {
  id: string
  type: string // NotificationType либо произвольный код бэкенда
  title: string
  body: string | null
  payload: Record<string, unknown> | null
  is_read: boolean
  is_broadcast: boolean
  created_at: string
}

// meta GET /notifications (unread_count — только свои непрочитанные).
export interface NotificationsMeta extends MetaPage {
  unread_count: number
}

export interface NotificationsPage {
  data: NotificationItem[]
  meta: NotificationsMeta
}

// ---------- Массовое добавление по SKU (SITEMAP `/bulk-add`, фича B) ----------

export interface BulkItemIn {
  sku: string
  qty: number
}

// Цена позиции из resolve-bulk (та же форма, что ProductCard).
export interface BulkPrice {
  base_price_byn: number
  retail_price: number
  client_price: number
  currency: string
  rate_source: string
  has_discount: boolean
}

export interface BulkResolveItem {
  sku: string
  qty: number
  found: boolean
  name: string | null
  price: BulkPrice | null
  stock_status: StockStatus | null
  error: string | null
}

export interface BulkResolveOut {
  data: BulkResolveItem[]
}

// POST /cart/items/bulk — всегда 200: часть позиций может быть отклонена.
export interface BulkCartAddOut {
  added: { sku: string; quantity: number }[]
  rejected: { sku: string; reason: string }[]
}

// ---------- Этап 7: Файловый архив (SITEMAP `/files`, `/manager/files`; §16 п.18) ----------

export type FileAssetType = 'BRAND_PDF' | 'CUSTOM_CSV' | 'PHOTO_ZIP' | 'OTHER'
export type FileVisibility = 'PUBLIC' | 'AUTHED' | 'MANAGER_ONLY'

export interface FileAsset {
  id: string
  type: FileAssetType
  filename: string
  content_type: string | null
  size_bytes: number
  brand_id: string | null
  brand_name: string | null
  visibility: FileVisibility
  created_at: string
}

export interface FileAssetPage {
  data: FileAsset[]
  meta: MetaPage
}

// GET /files/{id}/download → presigned URL (TTL 5 мин), обёрнут в {"data": ...}.
export interface FileDownloadOut {
  url: string
  expires_in: number
}

// ---------- Этап 8: Менеджер-панель — клиенты, курсы, аудит ----------

export type RateSource = 'NBRB' | 'MANUAL'

// Курс валюты (Decimal приходит строкой).
export interface RateOut {
  id: string
  currency_code: string
  rate: string
  scale: number
  fetched_at: string // ISO-дата YYYY-MM-DD
  source: RateSource
  is_manual: boolean
}

// Клиент в панели менеджера (GET /manager/users/{id}).
export interface UserManagerRead {
  id: string
  email: string
  full_name: string
  company: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  display_currency: string
  price_digest_enabled: boolean
  price_digest_sources: string[]
  consent_accepted_at: string | null
  created_at: string
  fixed_rate: RateOut | null
}

// Строка списка клиентов (GET /manager/users).
export interface UserManagerListItem {
  id: string
  email: string
  full_name: string
  company: string | null
  phone: string | null
  is_active: boolean
  display_currency: string
  created_at: string
  fixed_rate_currency: string | null
  avg_discount_percent: string | null
  orders_count: number
}

export interface UserManagerPage {
  data: UserManagerListItem[]
  meta: MetaPage
}

// Детали клиента: профиль + матрица скидок.
export interface DiscountOut {
  brand_id: string
  brand_name: string
  percent: string
}

export interface UserManagerDetail {
  user: UserManagerRead
  discounts: DiscountOut[]
}

// Создание клиента: 201 + временный пароль (показ один раз).
export interface UserManagerCreateOut {
  user: UserManagerRead
  temp_password: string
}

// --- Админ-панель (GET/POST/PATCH /admin/managers) ---
export interface AdminManagerListItem {
  id: string
  email: string
  full_name: string
  is_active: boolean
  created_at: string
}

export interface AdminManagerCreateOut {
  user: AdminManagerListItem
  temp_password: string
}

export interface TempPasswordOut {
  temp_password: string
}

// Запись журнала аудита (GET /manager/audit).
export interface AuditRead {
  id: string
  actor_id: string | null
  actor_email: string | null
  action: string
  target_type: string | null
  target_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  created_at: string
}

export interface AuditPage {
  data: AuditRead[]
  meta: MetaPage
}

// ---------- Этап 8 (фича G): менеджер — дашборд, каталог, бренды/серии ----------
// См. app/schemas/manager_catalog.py. Decimal приходит строкой (как в RateOut).

// GET /manager/dashboard — агрегаты за периоды, кэш на сервере 60 с.
export interface DashboardKpi {
  orders_today: number
  orders_7d: number
  revenue_month: string // BYN
  new_clients_7d: number
  active_imports: number
}

export interface OrdersByDayItem {
  date: string // YYYY-MM-DD, 30 дней по возрастанию
  count: number
}

export interface TopProductItem {
  product_id: string
  sku: string
  name: string
  qty: number
  revenue: string // BYN
}

export interface TopClientItem {
  client_id: string
  name: string
  orders: number
  revenue: string // BYN
}

export interface RecentOrderItem {
  id: string
  created_at: string
  client_name: string
  status: OrderStatus
  total_amount: string // BYN
  seq?: number | null
}

export interface DashboardData {
  kpi: DashboardKpi
  orders_by_day: OrdersByDayItem[]
  top_products: TopProductItem[]
  top_clients: TopClientItem[]
  recent_orders: RecentOrderItem[]
  // Акции/новинки (поля новые — бэкенд может ещё не отдавать).
  new_arrivals?: DashboardCarouselItem[]
  promos?: DashboardCarouselItem[]
}

// Товар каруселей «Акции»/«Новинки» дашборда (шейп ClientNewArrival/ClientPromo,
// app/schemas/dashboard.py). У менеджера в client_price — розничная цена BYN.
export interface DashboardCarouselItem {
  id: string
  sku: string
  name: string
  photo_key: string | null
  client_price: string
  currency: string
  has_discount: boolean
}

// Товар в панели менеджера (GET /manager/products): виден и ARCHIVED.
export interface ManagerProductRow {
  id: string
  sku: string
  name: string
  brand: BrandRef | null
  series: SeriesRef | null
  base_price: string // BYN
  override_price: string | null // ручная цена менеджера (null — нет)
  stock_status: StockStatus
}

export interface ManagerProductPage {
  data: ManagerProductRow[]
  meta: MetaPage
}

// PATCH /manager/products/{id}: override_price: null — явный сброс ручной цены;
// передать нужно хотя бы одно поле (иначе 422).
export interface ManagerProductPatchIn {
  override_price?: number | null
  stock_status?: StockStatus
}

// GET /manager/brands — плоский массив (без конверта).
export interface ManagerBrand {
  id: string
  name: string
  slug: string
  series_count: number
  products_count: number
}

// POST /manager/series/{id}/photo (multipart file) → ключ и URL фото серии.
export interface SeriesPhotoOut {
  photo_key: string
  photo_url: string
}

// ---------- Этап 12: Telegram Mini App (§16 п.27, SITEMAP §8) ----------

// POST /api/v1/auth/telegram/link-code (веб-кабинет): одноразовый 6-значный код,
// Redis TTL 10 мин. Вводится при первом входе в Mini App.
export interface TelegramLinkCode {
  code: string
  expires_in: number // секунды (600)
}

// Тело POST /api/m/v1/auth/telegram: подписанные initData + код связки (первый вход).
export interface TelegramAuthIn {
  init_data: string
  link_code?: string
}

// Успех POST /api/m/v1/auth/telegram: TokenPair + признак первого входа (линк по коду).
// applyTokens берёт access_token; user надёжнее получать отдельным fetchMe.
export interface MiniAppAuthResponse extends TokenPair {
  linked: boolean
  user?: UserPublic | null
}

// Отказы m-auth: 401 {detail, link_required: true} | 503 (не настроено) | 403 (MANAGER).
export interface TelegramLinkRequiredError {
  detail: string
  link_required: true
}

// ---------- Публичная SEO-витрина (/brands, SITEMAP §5; §16 п.29) ----------
// Без цен/остатков/ПДн. Ответы могут приходить в конверте {data: ...} (§6).

// GET /api/v1/public/brands → [{id, name, slug}].
export interface PublicBrand {
  id: string
  name: string
  slug: string
}

// Серия внутри GET /api/v1/public/brands/{slug}; photo_thumb — S3-ключ миниатюры
// (отдаётся через /api/v1/public/photo?key=), null — показываем заглушку.
export interface PublicSeriesRef {
  id: string
  name: string
  slug: string
  photo_thumb: string | null
}

// GET /api/v1/public/brands/{slug} → {id, name, slug, series: [...]}.
export interface PublicBrandDetail extends PublicBrand {
  series: PublicSeriesRef[]
}

// GET /api/v1/public/series/{slug}/products → [{sku, name}] (без цен/статусов).
export interface PublicSeriesProduct {
  sku: string
  name: string
}

// ---------- Новостная лента (GET /api/v1/news) ----------

export type NewsType = 'NEWS' | 'NEW_PRODUCT'

export interface NewsRead {
  id: string
  title: string
  content: string
  type: NewsType
  image_url: string | null
  published_at: string
}

export interface NewsPage {
  data: NewsRead[]
  meta: MetaPage
}

// ---------- Маркетинговые баннеры (GET /api/v1/banners, менеджерский CRUD) ----------

export type BannerLinkType = 'NONE' | 'PRODUCT' | 'NEWS'
export type BannerPosition = 'PROMO' | 'NEW'

// GET /api/v1/banners?position=promo|new — только активные, sort ASC.
export interface BannerRead {
  id: string
  title: string
  subtitle: string | null
  image_key: string | null
  link_type: BannerLinkType
  link_value: string | null
  position: BannerPosition
  sort: number
  is_active: boolean
}

// POST /api/v1/manager/banners — все поля обязательны (link_value/subtitle/image_key допускают null).
export interface BannerCreate {
  title: string
  subtitle: string | null
  image_key: string | null
  link_type: BannerLinkType
  link_value: string | null
  position: BannerPosition
  sort: number
  is_active: boolean
}

// PATCH /api/v1/manager/banners/{id} — частичный, все поля опциональны.
export type BannerUpdate = Partial<BannerCreate>
