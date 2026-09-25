import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Регрессионный страж маршрутного сплита:
//   /          — всегда публичный лендинг (без приватных запросов)
//   /dashboard — компактный клиентский дом (auth + CLIENT)
//   /analytics — «Моя аналитика» (auth + CLIENT)
// Файл проверяется по исходнику: страницы/миддлваре/robots — тонкие
// декларативные модули без экспортируемых констант.
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (relativePath: string) => readFileSync(resolve(webRoot, relativePath), 'utf8')

describe('route split: / is always the public landing', () => {
  const index = read('pages/index.vue')

  it('keeps the landing SEO, JSON-LD and public content blocks', () => {
    expect(index).toContain('application/ld+json')
    expect(index).toContain("'@type': 'FAQPage'")
    expect(index).toContain("rel: 'canonical'")
    expect(index).toContain('id="lead"') // лид-форма на месте
    expect(index).toContain('id="catalog-heading"')
    expect(index).toContain('<LandingTestimonials')
    expect(index).toContain('<ManagerContactModal')
  })

  it('does not branch into a client dashboard and fetches no private client data', () => {
    expect(index).not.toMatch(/v-else-if="isClient"/)
    expect(index).not.toContain('fetchMe')
    for (const privatePath of [
      "'/api/v1/orders'",
      "'/api/v1/favorites'",
      "'/api/v1/files'",
      "'/api/v1/banners'",
      "'/api/v1/dashboard'",
    ]) {
      expect(index).not.toContain(privatePath)
    }
  })
})

describe('route split: /dashboard is the compact client home', () => {
  const dashboard = read('pages/dashboard.vue')
  const component = read('components/client/ClientHomeDashboard.vue')

  it('is gated by auth + CLIENT role and uses the client layout', () => {
    expect(dashboard).toContain("layout: 'client'")
    expect(dashboard).toContain("middleware: ['auth', 'role']")
    expect(dashboard).toContain("roles: ['CLIENT']")
  })

  it('renders the extracted component with v2 orders and real dashboard documents', () => {
    expect(dashboard).toContain('<ClientHomeDashboard')
    expect(component).toContain('useOrdersV2()')
    expect(component).toContain('ordersV2.list({ limit: 5 })')
    expect(component).toContain('useCartV2()')
    expect(component).toContain("'/api/v1/dashboard'")
    expect(component).toContain("'/api/v1/files'")
    expect(component).toContain('Последние заявки')
    expect(component).toContain('Документы')
    expect(component).not.toContain('<HomeBanner')
  })
})

describe('route split: /analytics keeps the analytics implementation', () => {
  const analytics = read('pages/analytics.vue')

  it('is client-only, noindex via client layout, and loads the client dashboard API', () => {
    expect(analytics).toContain("layout: 'client'")
    expect(analytics).toContain("middleware: ['auth', 'role']")
    expect(analytics).toContain("roles: ['CLIENT']")
    expect(analytics).toContain("useHead({ title: 'Моя аналитика' })")
    expect(analytics).toContain("request<ClientDashboardData>('/api/v1/dashboard')")
  })

  it('is not marked indexable by the page itself (noindex comes from the client layout)', () => {
    expect(analytics).not.toContain("name: 'robots'")
  })
})

describe('route split: consent gate and robots', () => {
  it('skips the consent redirect for the public landing', () => {
    expect(read('middleware/consent.global.ts')).toMatch(/SKIP_PATHS\s*=\s*\['\/',/)
  })

  it('disallows the private client routes in robots.txt', () => {
    const robots = read('server/routes/robots.txt.ts')
    expect(robots).toContain("'/dashboard'")
    expect(robots).toContain("'/analytics'")
    // '/' остаётся публичным и не попадает в Disallow
    expect(robots).not.toContain("'/'")
    expect(read('server/routes/sitemap.xml.ts')).toContain("'/'")
  })
})
