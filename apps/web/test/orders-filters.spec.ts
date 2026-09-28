import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const readPage = (path: string) => readFileSync(resolve(webRoot, path), 'utf8')

// Статический контракт страницы (в стиле browser-client-catalog-pages):
// панель фильтров истории заявок синхронизируется с URL по образцу каталога.
const ordersPage = readPage('pages/orders/index.vue')

describe('client orders list filters', () => {
  it('restores filters from the URL query on page load (F5 survival)', () => {
    expect(ordersPage).toContain("const q = ref(queryString('q'))")
    expect(ordersPage).toContain("dateFrom: queryDate('date_from')")
    expect(ordersPage).toContain("dateTo: queryDate('date_to')")
    expect(ordersPage).toContain("minTotal: queryTotal('min_total')")
    expect(ordersPage).toContain("maxTotal: queryTotal('max_total')")
  })

  it('writes applied filters back into the URL on every list request', () => {
    expect(ordersPage).toContain('router.replace({ query: urlQuery })')
    expect(ordersPage).toContain('urlQuery.q = applied.q')
    expect(ordersPage).toContain('urlQuery.date_from = applied.dateFrom')
    expect(ordersPage).toContain('urlQuery.date_to = applied.dateTo')
    expect(ordersPage).toContain('urlQuery.min_total = applied.minTotal')
    expect(ordersPage).toContain('urlQuery.max_total = applied.maxTotal')
  })

  it('sends filter parameters to the v2 list endpoint', () => {
    expect(ordersPage).toContain('q: applied.q')
    expect(ordersPage).toContain('dateFrom: applied.dateFrom')
    expect(ordersPage).toContain('dateTo: applied.dateTo')
    expect(ordersPage).toContain('minTotal: applied.minTotal')
    expect(ordersPage).toContain('maxTotal: applied.maxTotal')
    expect(ordersPage).toContain('limit: PER_PAGE')
  })

  it('debounces text search and resets pagination on filter changes', () => {
    // ~300 мс, как поиск в каталоге.
    expect(ordersPage).toMatch(/setTimeout\(applyFilters,\s*300\)/)
    // Смена фильтров или статуса сбрасывает курсор и страницу на начало.
    expect(ordersPage).toMatch(/function applyFilters\(\)\s*\{\s*resetPosition\(\)/)
    expect(ordersPage).toMatch(/function applyStatus\([\s\S]*?resetPosition\(\)/)
    expect(ordersPage).toMatch(/function resetPosition\(\)\s*\{\s*page\.value = 1\s*cursorHistory = \[null\]/)
  })

  it('resets filters and the status tab to their defaults', () => {
    expect(ordersPage).toMatch(/function resetFilters\(\)[\s\S]*?q\.value = ''/)
    expect(ordersPage).toMatch(/function resetFilters\(\)[\s\S]*?filters\.dateFrom = ''/)
    expect(ordersPage).toMatch(/function resetFilters\(\)[\s\S]*?filters\.maxTotal = ''/)
    expect(ordersPage).toMatch(/function resetFilters\(\)[\s\S]*?statusFilter\.value = ''/)
  })

  it('shows a dedicated empty state when filters match nothing', () => {
    expect(ordersPage).toContain('data-testid="orders-empty-filtered"')
    expect(ordersPage).toContain('Ничего не найдено')
    expect(ordersPage).toContain('data-testid="orders-empty-reset"')
    // Базовая заглушка «заявок пока нет» остаётся для чистого списка.
    expect(ordersPage).toContain('data-testid="orders-empty"')
    expect(ordersPage).toMatch(/!orders\.length && !error && hasActiveFilters/)
  })

  it('keeps the filter panel usable on mobile widths', () => {
    expect(ordersPage).toContain('data-testid="orders-filter-panel"')
    expect(ordersPage).toMatch(/grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-6/)
  })
})
