import { expect, test } from '@playwright/test'
import { goto } from './support/nav'
import { MANAGER_STATE, MISSING_CREDENTIALS, hasManagerCredentials } from './support/auth'

// ============================================================
//  Каталог и карточка товара.
//
//  В задании этот сценарий стоял в public.spec, но /catalog и /catalog/[sku]
//  закрыты middleware: 'auth' (см. pages/catalog/index.vue), а /brands и /
//  публичны. Поэтому витрина без входа живёт в public.spec.ts, а каталог —
//  здесь, на сессии менеджера из global-setup.
//
//  SKU нигде не зашит: он берётся из реальной ссылки в таблице каталога.
//  Так тест переживает смену номенклатуры и не врёт на пустом стенде.
// ============================================================

test.use({ storageState: MANAGER_STATE })

test.beforeEach(() => {
  test.skip(!hasManagerCredentials(), MISSING_CREDENTIALS)
})

/** Таблица каталога — только на десктопной раскладке (xl ≥ 1280px). */
async function useDesktopViewport(page: import('@playwright/test').Page): Promise<void> {
  await page.setViewportSize({ width: 1440, height: 900 })
}

test.describe('каталог', () => {
  test('@smoke каталог открывается после входа и доезжает до данных', async ({ page }) => {
    await useDesktopViewport(page)
    await goto(page, '/catalog')

    await expect(page.getByTestId('catalog-page')).toBeVisible()

    // Поиск — основной вход в каталог, у него есть и label, и testid.
    await expect(page.getByTestId('catalog-search')).toBeVisible()
    await expect(page.getByTestId('catalog-search')).toHaveAttribute('type', 'search')

    // Либо номенклатура, либо осмысленное «ничего не найдено» — но не скелетоны.
    await expect(
      page
        .getByTestId('catalog-table')
        .or(page.getByText('Ничего не найдено', { exact: true }))
        .or(page.getByTestId('catalog-error')),
    ).toBeVisible({ timeout: 30_000 })

    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  })

  test('без входа каталог отправляет на форму входа', async ({ browser }) => {
    // Отдельный контекст с ЯВНО пустым состоянием. Просто browser.newContext()
    // не годится: Playwright подмешивает в него опции файла, включая
    // storageState: MANAGER_STATE, и «анонимный» контекст оказывается залогинен.
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await context.newPage()
    try {
      await goto(page, '/catalog')
      await expect(page).toHaveURL(/\/login(\?|$)/)
    } finally {
      await context.close()
    }
  })
})

test.describe('карточка товара', () => {
  test('@smoke товар открывается по SKU из каталога', async ({ page }) => {
    await useDesktopViewport(page)
    await goto(page, '/catalog')

    const productLink = page.locator('[data-testid^="catalog-row-"] a[href^="/catalog/"]').first()
    // Пустой стенд (без `make seed-catalog`) — это не падение теста, но и
    // не повод молча проходить: явно говорим, что сценарий не проверен.
    await test.skip(
      (await productLink.count()) === 0,
      'Каталог пуст: нет ни одного товара. Выполните `make seed-catalog`, чтобы проверить карточку.',
    )

    const sku = ((await productLink.getAttribute('href')) ?? '').split('/').pop() ?? ''
    await expect(sku).not.toBe('')
    await productLink.click()

    await expect(page).toHaveURL(new RegExp(`/catalog/${encodeURIComponent(sku)}$`))
    await expect(page.getByTestId('catalog-product-page')).toBeVisible()

    // Артикул виден как надзаголовок, название — заголовком страницы.
    await expect(page.getByTestId('catalog-product-page')).toContainText(sku)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Хлебные крошки' })).toBeVisible()

    // Состояния «товар не найден» / «недоступен» на живом товаре быть не должно.
    await expect(page.getByTestId('catalog-product-not-found')).toHaveCount(0)
    await expect(page.getByTestId('catalog-product-error')).toHaveCount(0)
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  })

  test('несуществующий SKU показывает «Товар не найден», а не пустую страницу', async ({ page }) => {
    // SKU латиницей: артикулы в этом проекте ASCII, и так проверка не зависит
    // от того, как конкретная версия Nuxt декодирует неASCII-параметр маршрута.
    await goto(page, '/catalog/E2E-NO-SUCH-SKU-0000')

    await expect(page.getByTestId('catalog-product-page')).toBeVisible()
    await expect(page.getByTestId('catalog-product-not-found')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Вернуться в каталог' })).toBeVisible()

    // Возврат в каталог по предложенной ссылке — тоже рабочий путь.
    await page.getByRole('link', { name: 'Вернуться в каталог' }).click()
    await expect(page).toHaveURL(/\/catalog$/)
  })
})