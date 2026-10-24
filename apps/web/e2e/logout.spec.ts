import { expect, test } from '@playwright/test'
import { goto } from './support/nav'
import { MISSING_CREDENTIALS, hasManagerCredentials, loginThroughUi } from './support/auth'

// ============================================================
//  Выход из кабинета.
//
//  Отдельный файл не из эстетики, а из-за устройства бэкенда: POST
//  /auth/logout ставит SessionModel.revoked и обесценивает refresh_token
//  СВОЕЙ сессии. Если прогонять этот тест на общей MANAGER_STATE, он
//  отозвал бы её и уронил все следующие файлы (catalog, manager) — они
//  получали бы /login. Здесь тест логинится сам: свой вход, своя сессия,
//  отзыв только её. Порядок запуска файлов роли не играет.
//
//  Плюс это единственное место, где вход делается дважды за прогон
//  (второй — global-setup). Лимит RATE_LIMIT_LOGIN = 5 попыток / 15 мин,
//  так что лишних входов в наборе быть не должно.
// ============================================================

test.beforeEach(() => {
  test.skip(!hasManagerCredentials(), MISSING_CREDENTIALS)
})

test('@smoke выход из кабинета закрывает доступ к менеджскому разделу', async ({ page }) => {
  await loginThroughUi(page)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Обзор')

  await page.getByRole('button', { name: 'Выйти' }).click()
  await expect(page).toHaveURL(/\/login(\?|$)/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Вход в кабинет')

  // Сессия должна быть аннулирована НА СЕРВЕРЕ, а не просто вычищена из стора:
  // возврат по прямой ссылке обязан снова потребовать входа. Это и есть
  // регресс-барьер, который ловит «выход только на клиенте».
  await goto(page, '/manager')
  await expect(page).toHaveURL(/\/login(\?|$)/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Вход в кабинет')
})