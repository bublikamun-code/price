import { expect, test } from '@playwright/test'
import { goto } from './support/nav'

// ============================================================
//  Публичная витрина — то, что видит анонимный посетитель.
//  Ни авторизации, ни сидов тут не нужно: страницы должны открываться
//  и корректно «успокаиваться» из состояния загрузки при любом состоянии БД.
//
//  Каталог товаров (/catalog) и карточка товара закрыты middleware: 'auth'
//  (см. pages/catalog/index.vue), поэтому проверяются в catalog.spec.ts
//  уже после входа.
// ============================================================

/** Секция/панель, которая прямо сейчас грузит данные. */
const busy = (page: import('@playwright/test').Page) => page.locator('[aria-busy="true"]')

test.describe('главная страница', () => {
  test('@smoke витрина открывается анонимному посетителю', async ({ page }) => {
    await goto(page, '/')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/закупают/i)
    // Русскоязычный портал: язык документа задаётся в nuxt.config → app.head.
    await expect(page.locator('html')).toHaveAttribute('lang', 'ru')

    // Главная не должна подсовывать гостю редирект на форму входа:
    // витрина публична, вход — по кнопке.
    expect(new URL(page.url()).pathname).toBe('/')

    // CTA отрисован в десктопной и мобильной версии hero — два одинаковых
    // доступных имени. Это норма для адаптива, поэтому берём первую.
    const cta = page.getByRole('link', { name: /Открыть каталог/i }).first()
    await expect(cta).toBeVisible()
    await expect(cta).toHaveAttribute('href', /^\/(brands|catalog|manager)$/)
  })

  test('@smoke витрина доходит от загрузки до итогового состояния', async ({ page }) => {
    await goto(page, '/')

    // Состав каталога приезжает с /api/v1/public/brands: пока грузим — aria-busy,
    // после — либо карточки брендов, либо честное «каталог недоступен».
    const showcase = page.locator('[aria-label="Состояние публичного каталога"]')
    await expect(showcase).toBeVisible()
    await expect(showcase.locator('[aria-busy="true"]')).toHaveCount(0)

    // Подпись под героем не должна навсегда застрять в «Загружаем…».
    await expect(page.getByText('Загружаем актуальный состав каталога')).toHaveCount(0)
    await expect(
      page.getByText(/позиций в открытом каталоге|Каталог временно недоступен/i).first(),
    ).toBeVisible()

    // Витрина обязана доехать до конца: «сырых» skeletons не остаётся.
    await expect(busy(page)).toHaveCount(0)
  })
})

test.describe('публичные разделы', () => {
  test('@smoke каталог брендов открывается и выходит из загрузки', async ({ page }) => {
    await goto(page, '/brands')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Каталоги брендов')

    // Либо список брендов, либо осмысленное пустое состояние — но не скелетоны.
    await expect(busy(page)).toHaveCount(0)
    await expect(
      page
        .getByRole('navigation', { name: 'Бренды' })
        .or(page.getByText('Скоро здесь появятся каталоги')),
    ).toBeVisible()
  })

  test('@smoke лента новостей открывается и выходит из загрузки', async ({ page }) => {
    await goto(page, '/news')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Новости')

    await expect(busy(page)).toHaveCount(0)
    // Либо карточки новостей, либо явное «пока нет» — оба состояния осмысленны.
    await expect(
      page.getByText('Новостей пока нет').first()
        .or(page.locator('main a').first()),
    ).toBeVisible()
  })

  test('политика конфиденциальности доступна без входа', async ({ page }) => {
    await goto(page, '/privacy')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
      'Политика конфиденциальности',
    )
    expect(new URL(page.url()).pathname).toBe('/privacy')
  })
})