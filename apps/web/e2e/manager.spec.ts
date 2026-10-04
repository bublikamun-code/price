import { expect, test } from '@playwright/test'
import { goto } from './support/nav'
import { MANAGER_STATE, MISSING_CREDENTIALS, hasManagerCredentials } from './support/auth'

// ============================================================
//  Менеджерский раздел.
//
//  Ценность здесь не в «страница открылась», а в двух вещах, которых
//  нет в apps/api/tests: браузерный путь до раздела и то, что страница
//  заявок честно показывает ЗАГРУЗКУ, а не «сырые» скелетоны.
//
//  Вход не делаем здесь — сессия уже сохранена global-setup. Это важно:
//  RATE_LIMIT_LOGIN = 5 попыток / 15 мин на IP, лишние входы его съедают.
// ============================================================

test.use({ storageState: MANAGER_STATE })

test.beforeEach(() => {
  test.skip(!hasManagerCredentials(), MISSING_CREDENTIALS)
})

test.describe('менеджерский раздел', () => {
  test('@smoke дашборд менеджера открывается и показывает KPI', async ({ page }) => {
    await goto(page, '/manager')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Обзор')

    const kpi = page.getByRole('region', { name: 'Ключевые показатели' })
    await expect(kpi).toBeVisible()
    // Плитки — ссылки на разделы («Заявки сегодня», «Активных импортов» …).
    await expect(kpi.getByRole('link')).not.toHaveCount(0)

    // Дошли до данных, а не застряли на скелетонах.
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  })

  test('@smoke список заявок открывается и выходит из состояния загрузки', async ({ page }) => {
    await goto(page, '/manager/orders')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Заявки')

    // Итог — либо таблица заявок, либо осмысленное пустое состояние.
    // Локаторы тут намеренно смысловые (роль/текст), а не data-testid:
    // так тест переживает вёрстку и не плодит разметку ради тестов.
    await expect(
      page
        .getByRole('table')
        .or(page.getByRole('heading', { name: 'Заявок пока нет' }))
        .or(page.getByRole('heading', { name: 'Ничего не найдено' })),
    ).toBeVisible({ timeout: 30_000 })
  })

  test('страница заявок отдаёт осмысленное, а не «сырое» состояние загрузки', async ({ page }) => {
    // Задерживаем ответ списка заявок, чтобы состояние загрузки гарантированно
    // попало в кадр: без этого оно проскакивает быстрее, чем успевает рендер.
    await page.route('**/api/v1/manager/orders**', async (route) => {
      const response = await route.fetch()
      await new Promise((resolve) => setTimeout(resolve, 1_500))
      await route.fulfill({ response })
    })

    await goto(page, '/manager/orders')

    const loading = page.getByTestId('manager-orders-loading')
    await expect(loading).toBeVisible()

    // «Сырое» состояние — это скелетоны без семантики. Проверяем, что у
    // загрузки есть роль статуса, признак занятости и текст для скринридера.
    await expect(loading).toHaveAttribute('aria-busy', 'true')
    await expect(loading).toHaveAttribute('aria-live', 'polite')
    await expect(loading.getByText('Загружаем список заявок…')).toBeAttached()
    // Декоративные скелетоны не должны попадать в дерево доступности.
    await expect(loading.locator('[aria-hidden="true"]')).toHaveCount(5)

    // …и что оно гарантированно сменяется итоговым состоянием.
    await expect(
      page.getByRole('table').or(page.getByTestId('manager-orders-empty')),
    ).toBeVisible({ timeout: 30_000 })
    await expect(loading).toHaveCount(0)
  })

  test('менеджер не попадает в клиентские разделы', async ({ page }) => {
    // RBAC через middleware/role: страница помечена roles: ['CLIENT'],
    // поэтому менеджеру отдаётся 403, а не редирект (см. middleware/role.ts).
    const response = await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })

    expect(response?.status()).toBe(403)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Недостаточно прав')
    await expect(page.getByText('У вас нет доступа к этому разделу')).toBeVisible()
    // Содержимое клиентского дашборда не должно подтекать в разметку.
    await expect(page.getByRole('heading', { name: /Добрый день/ })).toHaveCount(0)
  })

  test('поиск по заявкам доступен и подписан для скринридера', async ({ page }) => {
    await goto(page, '/manager/orders')

    // Поле подписано <label>, а не только placeholder'ом — ищем по доступному имени.
    const search = page.getByLabel('Поиск по номеру или клиенту')
    await expect(search).toBeVisible()
    await expect(search).toHaveAttribute('type', 'search')

    await search.fill('несуществующий-номер')
    await expect(
      page
        .getByText('Ничего не найдено')
        .or(page.getByTestId('manager-orders-empty'))
        .or(page.getByTestId('manager-orders-table')),
    ).toBeVisible({ timeout: 15_000 })
  })
})