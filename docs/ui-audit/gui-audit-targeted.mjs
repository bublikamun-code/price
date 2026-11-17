// Целевые проверки находок: воспроизведение конкретных кнопок со скриншотами.
// node /tmp/gui-audit/targeted.mjs
import { chromium } from 'playwright-core'

const BASE = 'https://localhost/price'
const SHOTS = '/data/bublik/projects/price/gui-audit-screens/ui-audit-2026-11-15/findings'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const MGR = { email: 'manager@example.com', password: 'JUXaGIyadDfc9tYL' }
const CLI = { email: 'client@priceweb.ru', password: 'SEmxa9BfVnXHmsex' }

async function login(page, c) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByLabel(/^Email/).fill(c.email)
  await page.getByLabel(/^Пароль/).fill(c.password)
  await page.getByRole('button', { name: /Продолжить/ }).click()
  await page.waitForTimeout(2500)
  if (page.url().includes('/force-change-password')) {
    await page.locator('#current-password').fill(c.password)
    await page.locator('#new-password').fill('ClientAudit2026')
    await page.locator('#confirm-password').fill('ClientAudit2026')
    await page.getByRole('button', { name: /Сменить|Изменить|Сохранить|Продолжить/ }).click()
    await page.waitForTimeout(2500)
  }
  return page.url()
}

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 }, locale: 'ru-RU' })
const page = await ctx.newPage()
page.on('dialog', (d) => d.accept().catch(() => {}))

const log = []

// --- 1. Менеджер: «Скачать счёт» на заявке (409, ошибка не показывается) ---
await login(page, MGR)
await page.goto(`${BASE}/manager/orders/b0db8268-0c06-4523-a636-ae217102d7f0`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2500)
const dl = page.locator('[data-testid="manager-invoice-download"]').first()
const dlCount = await dl.count()
const dlDisabled = dlCount ? await dl.isDisabled().catch(() => null) : null
await dl.click({ timeout: 5000 }).catch((e) => log.push(`клик «Скачать счёт»: ${e.message.split('\n')[0]}`))
await page.waitForTimeout(2500)
await page.screenshot({ path: `${SHOTS}/f1_manager_invoice_download_409.png` })
const alerts = await page.locator('[role="alert"], .badge-danger, .text-danger').allInnerTexts().catch(() => [])
log.push(`F1 менеджер «Скачать счёт»: найдено=${dlCount}; disabled=${dlDisabled}; видимых сообщений об ошибке: ${JSON.stringify(alerts)}`)

// --- 2. Клиент: «Повторить» на заявке другой организации (409) ---
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
await ctx.clearCookies()
await login(page, CLI)
await page.goto(`${BASE}/orders/b0db8268-0c06-4523-a636-ae217102d7f0`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2500)
await page.locator('[data-testid="order-detail-repeat"]').first().click({ timeout: 8000 }).catch((e) => log.push(`клик «Повторить»: ${e.message.split('\n')[0]}`))
await page.waitForTimeout(2500)
await page.screenshot({ path: `${SHOTS}/f2_client_repeat_409.png` })
const repeatMsg = await page.locator('[role="alert"], .badge-danger, .text-danger, p').allInnerTexts().catch(() => [])
log.push(`F2 клиент «Повторить»: страница=${page.url().replace(BASE, '')}; тексты с ошибкой: ${JSON.stringify(repeatMsg.filter((t) => /корзин|организац|повтор/i.test(t)).slice(0, 4))}`)

// --- 3. Менеджер: /profile — клиентский layout и 403 корзины ---
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
await ctx.clearCookies()
await login(page, MGR)
const cartCalls = []
page.on('response', (r) => {
  if (r.url().includes('/api/v2/cart')) cartCalls.push(`${r.status()} ${r.url().replace(BASE, '')}`)
})
page.on('console', (m) => { if (m.type() === 'error') log.push(`CONSOLE: ${m.text().slice(0, 120)}`) })
await page.goto(`${BASE}/profile`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3000)
await page.screenshot({ path: `${SHOTS}/f3_manager_profile_cart_403.png` })
log.push(`F3 менеджер /profile: запросы корзины: ${JSON.stringify(cartCalls)}`)
const cartUi = await page.locator('text=/ТЕКУЩАЯ ЗАЯВКА/i').allInnerTexts().catch(() => [])
log.push(`F3 элементы корзины в шапке менеджера: ${JSON.stringify(cartUi.slice(0, 2))}`)

console.log(log.join('\n'))
await browser.close()
