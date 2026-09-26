import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (path: string) => readFileSync(resolve(webRoot, path), 'utf8')
const templateOf = (path: string): string => {
  const source = read(path)
  return source.slice(source.indexOf('<template>'))
}
/** Nuxt регистрирует примитивы из components/ui только под именами Ui*. */
const UI_PRIMITIVE_NAMES = readdirSync(resolve(webRoot, 'components/ui'))
  .filter((file) => file.endsWith('.vue') && !file.startsWith('Ui'))
  .map((file) => file.replace(/\.vue$/, ''))

const app = read('app.vue')
const sheet = read('components/ui/Sheet.vue')
const focusTrap = read('composables/useFocusTrap.ts')
const productRecord = read('components/commerce/ProductRecordRow.vue')
const requestReview = read('components/commerce/RequestReviewSheet.vue')
const requestStrip = read('components/layout/CurrentRequestStrip.vue')
const landing = read('pages/index.vue')
const css = read('assets/css/main.css')
const landingCss = read('assets/css/landing.css')

describe('Trade presentation contract', () => {
  it('marks the production structural cutover in SSR output', () => {
    expect(app).toContain('data-trade-frontend="record-v2"')
    expect(app).toContain('bg-background')
  })

  it('keeps modal semantics, focus containment, Escape and focus restoration', () => {
    expect(sheet).toContain('role="dialog"')
    expect(sheet).toContain('aria-modal="true"')
    expect(sheet).toContain('@click="close"')
    expect(sheet).toContain("event.key === 'Escape'")
    expect(sheet).toContain('useFocusTrap(panel')
    expect(focusTrap).toContain("event.key !== 'Tab'")
    expect(focusTrap).toContain('previousFocus?.isConnected')
  })

  it('uses 44px touch targets for commerce row actions', () => {
    for (const source of [productRecord, requestReview]) {
      expect(source).not.toMatch(/<button\b[^>]*\bclass="[^"]*\bsize-(8|9|10)\b/)
      expect(source).toMatch(/<button\b[^>]*\bclass="[^"]*\bsize-11\b/)
    }
    expect(requestReview).toContain('min-h-11')
  })

  it('provides a persistent, named current-request entry point', () => {
    expect(requestStrip).toContain('Текущая заявка')
    expect(requestStrip).toContain('aria-label')
    expect(requestStrip).toContain('@click="openReview"')
  })

  it('reconstructs the public concept 05 Trade sections', () => {
    expect(landing).toContain('<div class="landing-trade">')
    expect(landing).toContain('<section class="hero section-wrap">')
    expect(landing).toContain('class="hero-panel"')
    expect(landing).toContain('<section class="signal-bar"')
    expect(landing).toContain('class="product-table"')
    expect(landing).toContain('id="brands" class="brands-section section-wrap"')
    expect(landing).toContain('id="delivery" class="delivery-section"')
    expect(landing).toContain('id="company" class="company-section section-wrap"')
    expect(landing).toContain('id="lead"')
    expect(landing).toContain('<LandingTestimonials')
    expect(landing).toContain('<ManagerContactModal')
  })

  it('uses fetched public brand data for every catalog surface', () => {
    expect(landing).toContain("request<{")
    expect(landing).toContain("'/api/v1/public/brands'")
    expect(landing).toContain('const heroBrands = computed')
    expect(landing).toContain('const catalogRows = computed')
    expect(landing).toContain('const wallBrands = computed')
    expect(landing).toContain('const catalogStats = computed')
    expect(landing).toContain('{{ formatCount(catalogStats.brands) }}')
    expect(landing).toContain('{{ formatCount(catalogStats.series) }}')
    expect(landing).toContain('{{ formatCount(catalogStats.products) }}')
    expect(landing).not.toContain('/api/v1/public/series/')
    expect(landing).not.toContain('v-for="product in')
  })

  it('keeps the landing free of demo stores, demo claims and private commerce APIs', () => {
    expect(landing).not.toContain('localStorage')
    expect(landing).not.toContain('useApiV2')
    expect(landing).not.toContain('useCartV2')
    expect(landing).not.toContain('Алексей Кравцов')
    expect(landing).not.toContain('4286')
    expect(landing).not.toContain('PricePortal · B2B-каталог')
  })

  it('isolates concept 05 Trade tokens and responsive geometry from the shared shell', () => {
    expect(landingCss).toContain('.landing-trade {')
    expect(landingCss).toContain('--landing-bg: #f5f2eb;')
    expect(landingCss).toContain('--landing-ink: #1b2a24;')
    expect(landingCss).toContain('--landing-accent: #c65c3b;')
    expect(landingCss).toContain('content: "DIRECT TRADE / 24"')
    expect(landingCss).toContain('box-shadow: 12px 12px 0 var(--landing-accent)')
    expect(landingCss).toContain('min-height: 506px;')
    expect(landingCss).toContain('grid-template-columns: 1fr 1.06fr;')
    expect(landingCss).toContain('grid-template-columns: repeat(4, 1fr);')
    expect(landingCss).toContain('@media (max-width: 1000px)')
    expect(landingCss).toContain('@media (max-width: 600px)')
    expect(landingCss).toContain('@media (prefers-reduced-motion: reduce)')
    expect(landingCss).not.toContain('Barlow Condensed')
    expect(css).not.toContain('Barlow+Condensed')
    expect(css).not.toContain('--color-landing-service:')
    expect(css).toContain('--color-service: 27 42 36;')
    expect(css).toContain('--color-service-2: 36 56 47;')
  })

  it('defines record primitives without decorative radii or effects', () => {
    expect(css).toContain('.record-list')
    expect(css).toContain('.service-record')
    expect(css).toContain('prefers-reduced-motion: reduce')
    expect(css).toContain('--radius-surface: 2px')
    expect(css).toContain('--radius-control: 0')
  })

  it('defines shared service, action, font and sticky primitives', () => {
    expect(css).toContain('--color-service-ink: 248 245 237;')
    expect(css).toContain('--color-service-muted: 175 187 177;')
    expect(css).toContain('--color-service-border: 86 110 98;')
    expect(css).toContain('--color-action-soft: 244 222 214;')
    expect(css).toContain("--font-sans: 'Manrope'")
    expect(css).toContain("--font-display: 'Manrope'")
    expect(css).toContain("--font-mono: 'IBM Plex Mono'")
    expect(css).toContain('--shadow-sticky: 0 -4px 16px')
  })

  it('uses the canonical toast viewport and shared empty states in migrated surfaces', () => {
    expect(app).toContain('<UiToastViewport />')
    expect(app).not.toContain('<ToastContainer />')
    expect(read('pages/favorites.vue')).toContain('<UiEmptyState')
    expect(read('pages/analytics.vue')).toContain('<UiEmptyState')
    expect(read('pages/analytics.vue')).toContain('<UiStatusBadge')
    expect(read('utils/order-status.ts')).toContain('export const ORDER_STATUS_META')
  })

  it('keeps the Mini App on its separate v1 channel and shared Trade primitives', () => {
    const miniCart = read('pages/m/cart.vue')
    const miniProduct = read('pages/m/catalog/[sku].vue')
    const miniNotifications = read('pages/m/notifications.vue')
    const miniLayout = read('layouts/miniapp.vue')
    for (const source of [miniCart, miniProduct, miniNotifications]) {
      expect(source).toContain('<PageHeading')
    }
    expect(miniProduct).toContain('<UiStatusBadge')
    expect(miniNotifications).toContain('<UiStatusBadge')
    expect(miniCart).toContain("'/api/v1/orders'")
    expect(miniCart).not.toContain('useApiV2')
    expect(miniCart).not.toContain('useCartV2')
    expect(miniLayout).toContain('env(safe-area-inset-bottom)')
    expect(miniLayout).not.toContain('text-[9px]')
    expect(miniLayout).not.toContain('text-[10px]')
  })
})

const CLIENT_FILES = [
  'layouts/auth.vue',
  'layouts/client.vue',
  'pages/login.vue',
  'pages/cart.vue',
  'pages/checkout.vue',
  'pages/favorites.vue',
  'pages/files.vue',
  'pages/analytics.vue',
  'pages/bulk-add.vue',
  'pages/catalog/index.vue',
  'components/layout/ClientHeader.vue',
  'components/layout/MobileClientHeader.vue',
  'components/layout/MobileClientNav.vue',
  'components/layout/StickyActionBar.vue',
  'components/client/CatalogFilters.vue',
  'components/ManagerContactModal.vue',
  'components/GlobalSearch.vue',
  'components/ui/ToastViewport.vue',
  'components/CookieConsentBanner.vue',
]

describe('Client cabinet contract', () => {
  it('keeps one H1 owner on auth screens at the documented 30/38 scale', () => {
    const authLayout = read('layouts/auth.vue')
    const pageHeading = read('components/layout/PageHeading.vue')
    expect(authLayout).not.toContain('<h1')
    expect(pageHeading).toContain('text-3xl font-bold leading-[1.27] text-ink')
    expect(pageHeading).toContain('<h1')
  })

  it('never renders client text below 12px', () => {
    for (const path of CLIENT_FILES) {
      const source = read(path)
      expect(source, path).not.toMatch(/text-\[(9|10|11)px\]/)
      expect(source, path).not.toMatch(/font-size="(9|10|11)"/)
    }
  })

  it('references UI primitives by their registered Ui* names', () => {
    const files = [
      ...CLIENT_FILES,
      'pages/notifications.vue',
      'components/client/ClientHomeDashboard.vue',
      'components/ui/Button.vue',
      'components/ui/Dialog.vue',
      'components/ui/ErrorState.vue',
      'components/ui/IconButton.vue',
      'components/ui/LoadingState.vue',
      'components/ui/Pagination.vue',
      'components/ui/Sheet.vue',
    ]
    for (const path of files) {
      const template = templateOf(path)
      for (const name of UI_PRIMITIVE_NAMES) {
        expect(template, `${path} → <${name}>`).not.toMatch(new RegExp(`<(/?)${name}(?=[\\s/>])`))
      }
    }
  })

  it('stacks the mobile bottom lanes from measured heights', () => {
    const stickyBar = read('components/layout/StickyActionBar.vue')
    const bottomLayers = read('composables/useBottomLayers.ts')
    const toast = read('components/ui/ToastViewport.vue')
    const cookies = read('components/CookieConsentBanner.vue')
    const checkout = read('pages/checkout.vue')

    expect(css).toContain('--h-mobile-nav: 4rem')
    expect(css).toContain('--bottom-nav-offset:')
    expect(stickyBar).toContain('var(--bottom-nav-offset)')
    expect(stickyBar).toContain('shadow-sticky')
    expect(bottomLayers).toContain('useNavLayer')
    expect(bottomLayers).toContain('useStickyLayer')
    expect(toast).toContain('stickyLayerHeight.value')
    expect(cookies).toContain('navLayerHeight.value')
    expect(checkout).toContain('<StickyActionBar')
    expect(checkout).not.toMatch(/fixed[^"]*bottom-16/)
  })

  it('opens catalog filters in a bottom sheet and keeps one current-request entry point', () => {
    const catalog = read('pages/catalog/index.vue')
    expect(catalog).toContain('<UiSheet')
    expect(catalog).toContain('side="bottom"')
    expect(catalog).toContain('<CatalogFilters')
    // Название компонента должно совпадать с зарегистрированным, иначе Vue
    // тихо рендерит пустой тег и фильтры исчезают (был такой баг на проде).
    expect(catalog).not.toContain('<ClientCatalogFilters')
    expect(catalog).toContain(':filters="filters"')
    expect(catalog).toContain('data-testid="catalog-filters"')
    expect(catalog).not.toContain('<CurrentRequestStrip')
    expect(catalog).toContain('to="/cart"')
    expect(catalog).toContain('data-testid="catalog-filters-open"')
  })

  it('routes both client headers through the shared global search', () => {
    for (const path of ['components/layout/ClientHeader.vue', 'components/layout/MobileClientHeader.vue']) {
      expect(read(path)).toContain('price:open-search')
    }
    expect(read('components/layout/ClientHeader.vue')).toContain('/profile#profile-currency')
  })

  it('renders favorites as records and files as table plus mobile records', () => {
    const favorites = read('pages/favorites.vue')
    const files = read('pages/files.vue')
    expect(favorites).toContain('<ProductRecordRow')
    expect(favorites).toContain('<UiPagination')
    expect(favorites).toContain('<UiErrorState')
    expect(favorites).toContain('data-testid="favorites-add-all"')
    expect(favorites).toContain("'/api/v1/favorites'")
    expect(favorites).not.toContain('aspect-square')
    expect(files).toContain('<UiTableFrame')
    expect(files).toContain('<UiPagination')
    expect(files).toContain('hidden md:block')
    expect(files).toContain('md:hidden')
    expect(files).not.toContain('<BaseSelect')
    expect(files).toContain("'/api/v1/files'")
    expect(files).toContain('/download`')
  })

  it('migrates the manager contact modal and login errors to shared form primitives', () => {
    const modal = read('components/ManagerContactModal.vue')
    const login = read('pages/login.vue')
    expect(modal).toContain('<UiDialog')
    expect(modal).toContain('<UiField')
    expect(modal).toContain('<UiInput')
    expect(modal).toContain('<UiTextarea')
    expect(modal).toContain("'/api/v1/public/lead'")
    expect(modal).not.toContain('<Teleport')
    expect(modal).not.toContain('document.body.style.overflow')
    expect(login).toContain('data-testid="login-error"')
    expect(login.match(/:error="errorMsg \|\| undefined"/g) ?? []).toHaveLength(1)
  })

  it('shows a real product photo with an icon fallback in request lines', () => {
    const line = read('components/commerce/OrderLineRecord.vue')
    const photo = read('composables/useLinePhoto.ts')
    // Фото приходит из v1-каталога по артикулу: v2-контракт медиа не несёт.
    expect(photo).toContain('/api/v1/catalog/products/')
    expect(photo).toContain('import.meta.server')
    expect(line).toContain('useLinePhoto')
    expect(line).toContain('<img')
    expect(line).toContain('@error="photoFailed = true"')
    // Иконка остаётся только как фолбэк, а не вместо фото.
    expect(line).toContain('<Icon v-else name="heroicons:package"')
    expect(line).not.toMatch(/<Icon name="heroicons:package"/)
  })

  it('renders the in-stock badge as adjacent-button segments everywhere it appears', () => {
    const badge = read('components/commerce/StockBadge.vue')
    const line = read('components/commerce/OrderLineRecord.vue')
    const detail = read('pages/catalog/[sku].vue')
    const catalog = read('pages/catalog/index.vue')
    // Соседние сегменты в одной рамке с разделителями, без скруглений.
    expect(badge).toContain('border-l border-border')
    expect(badge).toContain('overflow-hidden border border-border-strong')
    expect(badge).toContain('role="img"')
    expect(badge).toContain('В наличии')
    expect(badge).toContain('Под заказ')
    // Строка заявки и обе точки каталога используют сегментированный бейдж,
    // а не одиночный UiStatusBadge-пилюлю.
    expect(line).toContain('<StockBadge')
    expect(line).not.toContain('<UiStatusBadge')
    expect(detail).toContain('<StockBadge')
    expect(catalog).toContain('<StockBadge')
    expect(detail).not.toContain('<UiStatusBadge')
    expect(catalog).not.toContain('<UiStatusBadge')
  })
})
