// ============================================================
//  globalSetup: один вход менеджера на весь прогон.
//
//  Зачем: /api/v1/auth/login ограничен rate-limit'ом (RATE_LIMIT_LOGIN,
//  по умолчанию 5 попыток / 15 минут на IP). Если каждый spec логинится
//  сам, набор из ~6 входов гарантированно упрётся в лимит и начнёт
//  флакать на ровном месте. Здесь вход ровно один, результат кладётся
//  в storageState, который подхватывают spec-файлы через test.use().
//
//  auth.spec вход делает сам — ему это и есть предмет проверки.
// ============================================================

import { mkdirSync } from 'node:fs'
import { writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { chromium } from '@playwright/test'
import { MANAGER_STATE, hasManagerCredentials, loginThroughUi } from './support/auth'
import { chromiumLaunchOptions } from './support/browser'

export default async function globalSetup(): Promise<void> {
  mkdirSync(dirname(MANAGER_STATE), { recursive: true })

  // Без сидов/учётных данных пишем ПУСТОЕ состояние: контексты создадутся,
  // а требующие входа тесты пропустятся через test.skip в beforeEach.
  if (!hasManagerCredentials()) {
    await writeFile(MANAGER_STATE, JSON.stringify({ cookies: [], origins: [] }), 'utf8')
    return
  }

  const browser = await chromium.launch(chromiumLaunchOptions())
  try {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL })
    const page = await context.newPage()
    await loginThroughUi(page)
    await writeFile(MANAGER_STATE, JSON.stringify(await context.storageState()), 'utf8')
  } finally {
    await browser.close()
  }
}