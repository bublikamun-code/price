import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const readPage = (path: string) => readFileSync(resolve(webRoot, path), 'utf8')

const catalogList = readPage('pages/catalog/index.vue')
const catalogDetail = readPage('pages/catalog/[sku].vue')
const productRecord = readPage('components/commerce/ProductRecordRow.vue')
const favorites = readPage('pages/favorites.vue')
const bulkAdd = readPage('pages/bulk-add.vue')
const catalogFilters = readPage('components/client/CatalogFilters.vue')
const ownedPages = [catalogList, catalogDetail, favorites, bulkAdd]

describe('browser client catalog and cart writers', () => {
  it('routes catalog reads through the strict v2 repository', () => {
    for (const page of [catalogList, catalogDetail]) {
      expect(page).toContain('createCatalogRepository(useApiV2())')
      expect(page).not.toContain('/api/v1/catalog/products')
      expect(page).not.toMatch(/\buseCart\(/)
    }

    expect(catalogList).toContain('repository.search(q.value, query)')
    expect(catalogList).toContain('repository.list(')
    expect(catalogList).toMatch(/priceCalcMode\s*:\s*['"]fixed['"]/)
    expect(catalogList).toContain('currentCursor.value')
    expect(catalogList).toContain('nextCursor.value')
    expect(catalogDetail).toMatch(
      /repository\.getBySku\(sku\.value\s*,\s*['"]fixed['"]\)/,
    )
    expect(catalogDetail).toContain('series: [result.product.series.id]')
  })

  it('uses neutral media placeholders and never handles internal media keys', () => {
    for (const page of ownedPages) {
      expect(page).not.toContain('photo_key')
      expect(page).not.toContain('photoKey')
      expect(page).not.toContain('useProductPhoto')
    }

    // Кадр приходит из v2-контракта как стабильный media-ресурс; разбирает его
    // ProductPhoto, сама строка только передаёт thumbnail, а S3-ключи не видит.
    expect(catalogList).toContain('<ProductRecordRow')
    expect(productRecord).toContain('<ProductPhoto')
    expect(productRecord).toContain(':media="product.thumbnail"')
    expect(productRecord).not.toContain('heroicons:photo')
    expect(catalogDetail).toContain('catalog-product-media')
    expect(favorites).toContain('<ProductRecordRow')
    expect(favorites).toContain('test-id-prefix="favorite"')
  })

  it('writes every owned cart page through session-ready v2 UUID mutations', () => {
    for (const page of ownedPages) {
      expect(page).toContain('useCartV2()')
      expect(page).toContain('cartV2.ensureReady()')
      expect(page).toContain('catalogProductIdSchema.parse')
      expect(page).not.toMatch(/\buseCart\(/)
      expect(page).not.toContain('/api/v1/cart')
    }

    expect(catalogList).toContain('cartV2.replaceItem(productId, { quantity })')
    expect(catalogDetail).toContain(
      'cartV2.addItem({ productId, quantity: cartQuantity(qty.value) })',
    )
    expect(favorites).toContain('cartV2.addItem({')
    expect(bulkAdd).toContain('cartV2.addItem({')
  })

  it('resolves bulk rows to v2 product IDs and serializes fallback mutations', () => {
    expect(bulkAdd).not.toContain('/api/v1/cart/items/bulk')
    expect(bulkAdd).not.toContain('/api/v1/catalog/resolve-bulk')
    expect(bulkAdd).toMatch(
      /repository\.getBySku\(item\.sku\s*,\s*['"]fixed['"]\)/,
    )
    expect(bulkAdd).toContain('productId: product.id')
    expect(bulkAdd).toContain('enqueueCartMutation')
    expect(bulkAdd).toContain('await cartV2.addItem({')
    expect(bulkAdd).toContain('row.selected = false')
    expect(bulkAdd).toContain('retailPrice: product.retailPrice')
    expect(bulkAdd).toContain('result.failed.push')
  })

  it('keeps stable selectors for loading, empty, error, quantity, and write actions', () => {
    expect(catalogList).toContain('data-testid="catalog-page"')
    expect(catalogList).toContain('data-testid="catalog-error"')
    expect(catalogList).toContain('data-testid="catalog-pagination"')
    expect(catalogFilters).toContain('Любое наличие')
    expect(catalogDetail).toContain('data-testid="catalog-product-error"')
    expect(favorites).toContain('data-testid="favorites-add-all"')
    expect(bulkAdd).toContain('data-testid="bulk-add-submit"')
  })
})
