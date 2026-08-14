// Типы API-контрактов. См. ARCHITECTURE_PLAN.md §6, app/schemas/.
// Auth — плоский ответ; catalog — конверт {data, meta}.

export type UserRole = 'CLIENT' | 'MANAGER'
export type StockStatus = 'IN_STOCK' | 'PREORDER' | 'ARCHIVED'

export interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
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
  // Дайджест изменения цен (in-app уведомления). См. PATCH /api/v1/auth/me.
  price_digest_enabled: boolean
  price_digest_sources: string[] // только 'cart' | 'favorite' | 'orders'
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
}

export interface ProductDetail extends ProductCard {
  override_price: number | null
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
}

export interface PriceListVersionPage {
  data: PriceListVersionRead[]
  meta: MetaPage
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
  client_id: string
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
