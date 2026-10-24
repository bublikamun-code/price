// ============================================================
//  Общие помощники E2E: учётные данные менеджера и вход через UI.
//
//  Пароль НИКОГДА не хардкодится. Берём из окружения; если переменных
//  нет — тесты, которым нужен вход, пропускаются (test.skip), чтобы
//  CI без засеянного стенда был зелёным, а не красным.
// ============================================================

import { resolve } from 'node:path'
import { expect, type Page } from '@playwright/test'
import { goto } from './nav'

/** E2E_* имеют приоритет над SEED_* — так удобнее гонять против своего стенда. */
export const MANAGER_EMAIL = (
  process.env.E2E_MANAGER_EMAIL ?? process.env.SEED_MANAGER_EMAIL ?? ''
).trim()
export const MANAGER_PASSWORD = process.env.E2E_MANAGER_PASSWORD ?? process.env.SEED_MANAGER_PASSWORD ?? ''

export const MISSING_CREDENTIALS =
  'Нет учётных данных менеджера: задайте E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD ' +
  '(или SEED_MANAGER_EMAIL/SEED_MANAGER_PASSWORD из .env) и засейте стенд — ' +
  'тесты, требующие входа, пропущены.'

export function hasManagerCredentials(): boolean {
  return Boolean(MANAGER_EMAIL && MANAGER_PASSWORD)
}

/**
 * Файл сохранённой сессии менеджера. Пишет global-setup (один вход на прогон),
 * читают spec-файлы через `test.use({ storageState: MANAGER_STATE })`.
 * Файл всегда существует: без учётных данных туда кладётся пустое состояние,
 * поэтому конфиг не падает на отсутствии пути.
 */
export const MANAGER_STATE = resolve(process.cwd(), 'e2e/.artifacts/state/manager.json')

/** Кнопка отправки формы входа; в ожидании ответа её текст меняется. */
const SUBMIT = 'Продолжить'

/**
 * Вход менеджера через настоящую форму. Используется и global-setup,
 * и auth.spec — путь один, поэтому тест проверяет ровно то поведение,
 * на которое рассчитан остальной набор.
 *
 * Бросает осмысленную ошибку, если вход не завершился: неверные данные,
 * сработавший rate-limit (RATE_LIMIT_LOGIN — 5 попыток / 15 мин) или
 * включённая принудительная смена пароля.
 */
export async function loginThroughUi(page: Page): Promise<void> {
  await goto(page, '/login')
  await page.getByLabel(/^Email/).fill(MANAGER_EMAIL)
  await page.getByLabel(/^Пароль/).fill(MANAGER_PASSWORD)
  await page.getByRole('button', { name: SUBMIT }).click()

  const error = page.getByTestId('login-error')
  try {
    // Успех — уход на /manager; провал — появление сообщения под формой.
    await Promise.race([
      page.waitForURL(/\/manager(\?|$|#)/, { timeout: 20_000 }),
      error.waitFor({ state: 'visible', timeout: 20_000 }),
    ])
  } catch {
    throw new Error(
      `Вход менеджера не завершился, остались на ${page.url()}. ` +
        'Проверьте SEED_MANAGER_* и лимит попыток входа (RATE_LIMIT_LOGIN).',
    )
  }

  if (await error.isVisible()) {
    throw new Error(`Вход отклонён, на странице: ${(await error.innerText()).trim()}`)
  }
  if (page.url().includes('/force-change-password')) {
    throw new Error(
      'У менеджера включена принудительная смена пароля (must_change_password): ' +
        'для E2E её нужно снять.',
    )
  }
  await expect(page).toHaveURL(/\/manager(\?|$|#)/)

  // Гонка, из-за которой storageState сохранялся ПУСТЫМ и все залогиненные
  // спеки падали на /login: Nuxt уходит на /manager ещё на SSR, а клиентская
  // persistCookie() дописывает auth_user в document.cookie только после
  // гидрации. Если снять состояние раньше — cookie в него не попадёт.
  await page.waitForFunction(() => document.cookie.includes('auth_user='), undefined, {
    timeout: 20_000,
  })
}