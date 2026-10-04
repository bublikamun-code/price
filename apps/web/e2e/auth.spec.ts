import { expect, test } from '@playwright/test'
import { goto } from './support/nav'
import {
  MANAGER_EMAIL,
  MANAGER_STATE,
  MISSING_CREDENTIALS,
  hasManagerCredentials,
} from './support/auth'

// ============================================================
//  Вход менеджера.
//
//  Эти сценарии backend-тестами НЕ покрыты: apps/api/tests проверяет
//  контракт /auth/*, но не то, что браузерный путь «форма → редирект →
//  закрытые разделы» реально работает.
//
//  ДВА ОГРАНИЧЕНИЯ СТЕНДА, из-за которых набор устроен именно так:
//
//  1. RATE_LIMIT_LOGIN = 5 попыток / 15 мин на IP. Вход делает global-setup
//     (он же — единственный, кто идёт через настоящую форму), остальные
//     файлы берут готовую сессию из MANAGER_STATE.
//  2. Выход отзывает серверную сессию (SessionModel.revoked) и обесценивает
//     её refresh_token — общую MANAGER_STATE он портит. Поэтому проверка
//     выхода живёт отдельным файлом logout.spec.ts и логинится заново:
//     свой вход, своя сессия, отзыв только её.
// ============================================================

const WRONG_PASSWORD = 'definitely-not-the-password-0'

test.beforeEach(() => {
  test.skip(!hasManagerCredentials(), MISSING_CREDENTIALS)
})

test.describe('вход', () => {
  test('@smoke неверный пароль не пускает в кабинет', async ({ page }) => {
    await goto(page, '/login')

    await page.getByLabel(/^Email/).fill(MANAGER_EMAIL)
    await page.getByLabel(/^Пароль/).fill(WRONG_PASSWORD)
    await page.getByRole('button', { name: 'Продолжить' }).click()

    // Ошибка — role="alert", её читает скринридер: проверяем доступное имя.
    const error = page.getByRole('alert').filter({ hasText: 'Неверный email или пароль' })
    await expect(error).toBeVisible()
    expect(new URL(page.url()).pathname).toBe('/login')

    // Главный регресс-барьер: неудачный вход не должен оставить сессию.
    await goto(page, '/manager')
    await expect(page).toHaveURL(/\/login(\?|$)/)
  })

  test('защищённый раздел без сессии отправляет на форму входа', async ({ page }) => {
    await goto(page, '/manager')

    await expect(page).toHaveURL(/\/login(\?|$)/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Вход в кабинет')
    // Возвращаем адрес, откуда пришли, — без него пользователь теряет контекст.
    expect(page.url()).toContain('redirect=')
  })
})

test.describe('кабинет менеджера', () => {
  // Сессия создана реальным входом через форму (global-setup → loginThroughUi).
  test.use({ storageState: MANAGER_STATE })

  test('@smoke менеджер после входа попадает в свой раздел', async ({ page }) => {
    await goto(page, '/manager')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Обзор')

    // Менеджерский каркас на месте: разделы в сайдбаре и кнопка выхода.
    // <aside aria-label> — это landmark complementary, а не navigation,
    // и пункты меню надо искать внутри него, иначе strict mode спотыкается
    // о KPI-плитки «Заявки сегодня» / «Заявки за 7 дней».
    const sidebar = page.getByRole('complementary', { name: 'Разделы управления' })
    await expect(sidebar).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'Заявки', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Выйти' })).toBeVisible()
  })
})