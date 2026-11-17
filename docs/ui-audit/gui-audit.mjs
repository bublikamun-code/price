// ============================================================
//  GUI-аудитор клиентского и менеджерского кабинетов.
//
//  Что делает:
//   1. Заходит на живой стенд под реальной учёткой (клиент / менеджер).
//   2. Обходит список роутов кабинета, на каждой странице:
//      - снимает статические дефекты (console errors, pageerrors, HTTP >= 400,
//        битые картинки, горизонтальный оверфлоу, кнопки без доступного имени);
//      - снимает инвентарь всех интерактивных элементов;
//      - кликает по каждому элементу (деструктивные — в последнюю очередь),
//        фиксируя ошибки и реакцию UI;
//      - делает скриншот страницы и скриншот каждого дефекта.
//   3. Пишет JSON + сводку.
//
//  Запуск: node /tmp/gui-audit/audit.mjs [group]   (group: client|manager|public|mobile)
//
//  Ограничения по дизайну:
//   - элементы, уводящие с текущей страницы, после клика страница восстанавливается;
//   - «Выход» из кабинета не кликается в общем проходе (ломает сессию) — проверяется отдельно;
//   - нативные confirm/alert подтверждаются (действие реально выполняется).
// ============================================================

import { chromium } from 'playwright-core'
import { writeFileSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE || 'https://localhost/price'
const SHOTS = process.env.SHOTS || '/data/bublik/projects/price/gui-audit-screens/ui-audit-2026-11-15'
const OUT = process.env.OUT || '/tmp/gui-audit/result.json'
const ONLY = process.argv[2] || 'all'

const MANAGER = { email: 'manager@example.com', password: process.env.MGR_PW || 'JUXaGIyadDfc9tYL' }
const CLIENT = {
  email: 'client@priceweb.ru',
  password: process.env.CLIENT_PW || 'tNYc3yPg0-zgyoXV',
  passwords: [
    process.env.CLIENT_NEW_PW || 'ClientAudit2026',
    process.env.CLIENT_PW || 'tNYc3yPg0-zgyoXV',
  ],
  newPassword: process.env.CLIENT_NEW_PW || 'ClientAudit2026',
}

mkdirSync(SHOTS, { recursive: true })

// ---------------------------------------------------------------- утилиты

const slug = (u) => u.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_|_$/g, '') || 'root'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const DESTRUCTIVE_RE =
  /(удал|откат|отозв|деактив|сброс|очист|отклон|аннулир|блокир|закрыть доступ|отзыв)/i
const LOGOUT_RE = /(выйти|выход|logout|закончить сеанс)/i
const SKIP_HREF = /^(mailto:|tel:|javascript:|#)/i

function severityOf(text, status) {
  if (status >= 500) return 'Critical'
  if (/error/i.test(text) && status >= 400) return 'High'
  if (status === 404) return 'Medium'
  return 'High'
}

/** Собиратели событий страницы. Один бакет на страницу-обход. */
function attachCollectors(page) {
  const bucket = { console: [], pageerrors: [], http: [], failed: [] }
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      bucket.console.push({ type: m.type(), text: m.text().slice(0, 400) })
    }
  })
  page.on('pageerror', (e) => bucket.pageerrors.push(String(e.message || e).slice(0, 400)))
  page.on('response', async (r) => {
    const s = r.status()
    if (s >= 400) {
      bucket.http.push({ status: s, url: r.url().replace(BASE, ''), method: r.request().method() })
    }
  })
  page.on('requestfailed', (r) => {
    const f = r.failure()
    bucket.failed.push({ url: r.url().replace(BASE, ''), error: f ? f.errorText : 'unknown' })
  })
  return {
    bucket,
    drain() {
      const out = {
        console: bucket.console.splice(0),
        pageerrors: bucket.pageerrors.splice(0),
        http: bucket.http.splice(0),
        failed: bucket.failed.splice(0),
      }
      return out
    },
  }
}

/** Вход через настоящую форму. Принимает список паролей — temp и новый. */
async function login(page, creds) {
  const pwds = creds.passwords || [creds.password]
  for (const pwd of pwds) {
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
    await page.getByLabel(/^Email/).fill(creds.email)
    await page.getByLabel(/^Пароль/).fill(pwd)
    await page.getByRole('button', { name: /Продолжить/ }).click()
    await page.waitForTimeout(2500)
    if (page.url().includes('/force-change-password')) {
      await page.locator('#current-password').fill(pwd)
      await page.locator('#new-password').fill(creds.newPassword)
      await page.locator('#confirm-password').fill(creds.newPassword)
      await page.getByRole('button', { name: /Сменить|Изменить|Сохранить|Продолжить/ }).click()
      await page.waitForTimeout(2500)
    }
    if (!page.url().includes('/login')) return page.url()
  }
  return page.url()
}

/** Cookie-баннер мешает кликам — убираем. */
async function dismissCookieBanner(page) {
  const btn = page.getByRole('button', { name: /^Принять$/ })
  if (await btn.isVisible().catch(() => false)) {
    await btn.click().catch(() => {})
    await sleep(300)
  }
}

/** Внедрить data-audit-id во все видимые интерактивные элементы. */
async function injectIds(page) {
  return page.evaluate(() => {
    // снимаем прошлые метки: набор видимых элементов меняется, старые id
    // остались бы на скрытых элементах и давали бы дубликаты при поиске
    for (const old of document.querySelectorAll('[data-audit-id]')) old.removeAttribute('data-audit-id')
    const sel = 'a[href], button, input, textarea, select, [role="button"], [role="tab"], [role="switch"], summary, label[for]'
    const nodes = [...document.querySelectorAll(sel)].filter((n) => {
      const st = getComputedStyle(n)
      if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') return false
      if (n.hasAttribute('disabled') || n.getAttribute('aria-disabled') === 'true') return false
      if (n.closest('[aria-hidden="true"]')) return false
      const r = n.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) return false
      return true
    })
    nodes.forEach((n, i) => n.setAttribute('data-audit-id', String(i)))
    const seen = new Map()
    return nodes.map((n, i) => {
      const labelText = n.id
        ? (document.querySelector(`label[for="${CSS.escape(n.id)}"]`)?.innerText || '')
        : ''
      const name =
        (n.getAttribute('aria-label') ||
          n.innerText ||
          n.value ||
          labelText ||
          n.getAttribute('placeholder') ||
          n.getAttribute('title') ||
          '').replace(/\s+/g, ' ').trim()
      const tag = n.tagName.toLowerCase()
      const base = `${tag}|${name}`
      const occ = seen.get(base) || 0
      seen.set(base, occ + 1)
      return {
        id: i,
        key: `${base}#${occ}`,
        tag,
        type: n.getAttribute('type') || '',
        name: name.slice(0, 90),
        href: n.getAttribute('href') || '',
        label: n.getAttribute('for') || '',
        emptyName: !name && n.tagName !== 'INPUT',
      }
    })
  })
}

/** Статические проверки страницы (без кликов). */
async function staticChecks(page) {
  return page.evaluate(() => {
    const out = { overflow: null, brokenImages: [], unnamedButtons: [], emptyLabels: [] }
    const de = document.documentElement
    out.overflow = {
      scrollWidth: de.scrollWidth,
      innerWidth: window.innerWidth,
      overflowBy: de.scrollWidth - window.innerWidth,
    }
    for (const img of document.querySelectorAll('img')) {
      if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) {
        out.brokenImages.push((img.getAttribute('src') || '').slice(0, 160))
      }
    }
    for (const el of document.querySelectorAll('button, a[href], [role="button"]')) {
      const st = getComputedStyle(el)
      if (st.display === 'none' || st.visibility === 'hidden') continue
      const r = el.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) continue
      const name = (el.getAttribute('aria-label') || el.innerText || el.title || '').trim()
      if (!name) out.unnamedButtons.push(el.outerHTML.slice(0, 120))
    }
    for (const el of document.querySelectorAll('input, select, textarea')) {
      const id = el.id
      if (!id) continue
      const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`)
      if (!lab) {
        const ph = el.getAttribute('placeholder')
        if (!ph) out.emptyLabels.push(`${el.tagName.toLowerCase()}#${id}`)
      }
    }
    return out
  })
}

async function visibleDialog(page) {
  for (const sel of ['[role="dialog"]', 'dialog[open]', '.modal', '[data-testid*="modal"]']) {
    const loc = page.locator(sel).first()
    if (await loc.isVisible().catch(() => false)) return sel
  }
  return null
}

async function closeDialog(page) {
  await page.keyboard.press('Escape').catch(() => {})
  await sleep(350)
  if (await visibleDialog(page)) {
    const closers = page.locator('[role="dialog"] button[aria-label*="акрыть" i], [role="dialog"] button[aria-label*="lose" i], .modal button:has-text("×"), .modal button:has-text("✕")')
    const n = await closers.count()
    if (n > 0) await closers.first().click().catch(() => {})
    else await page.locator('[role="dialog"] button').first().click().catch(() => {})
    await sleep(350)
  }
}

/** Основной обход одной страницы. */
async function auditRoute(page, role, url, opts = {}) {
  const report = { role, url, issues: [], artifacts: [], inventory: [], clicks: [], screenshots: [] }
  const collectors = attachCollectors(page)

  let loadOk = true
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {})
    await sleep(350)
  } catch (e) {
    loadOk = false
    report.issues.push({ severity: 'Critical', type: 'Навигация', detail: `страница не открылась: ${String(e.message).slice(0, 200)}` })
  }

  if (!loadOk) return report

  await dismissCookieBanner(page)

  // --- статические дефекты ---
  const st = await staticChecks(page)
  if (st.overflow && st.overflow.overflowBy > 2) {
    report.issues.push({
      severity: 'Medium',
      type: 'Вёрстка',
      detail: `горизонтальный оверфлоу: +${st.overflow.overflowBy}px (scrollWidth ${st.overflow.scrollWidth} > ${st.overflow.innerWidth})`,
    })
  }
  for (const src of st.brokenImages) {
    report.issues.push({ severity: 'High', type: 'Изображение', detail: `битая картинка: ${src}` })
  }
  for (const html of st.unnamedButtons) {
    report.issues.push({ severity: 'Low', type: 'A11y', detail: `кнопка без доступного имени: ${html}` })
  }
  for (const id of st.emptyLabels) {
    report.issues.push({ severity: 'Low', type: 'A11y', detail: `поле без label/placeholder: ${id}` })
  }

  // --- скриншот страницы ---
  const shotName = `${role}__${slug(url)}.png`
  await page.screenshot({ path: `${SHOTS}/${shotName}`, fullPage: false }).catch(() => {})
  report.screenshots.push(shotName)

  // --- инвентарь ---
  const all = await injectIds(page)
  // Проверка видимости средствами самого Playwright: самописный фильтр по
  // computed style пропускает скрытые мобильные дубли разметки.
  const els = []
  for (const el of all) {
    const loc = page.locator(`[data-audit-id="${el.id}"]`)
    const visible = await loc.isVisible().catch(() => false)
    if (visible) els.push(el)
  }
  report.inventory = els
  const collectorIssues = collectors.drain()
  const isArtifact = (t) => /net::ERR_ABORTED|net::ERR_FAILED|Failed to load resource/i.test(t)
  for (const c of collectorIssues.console.filter((c) => c.type === 'error')) {
    if (isArtifact(c.text)) report.artifacts.push(c.text)
    else report.issues.push({ severity: 'High', type: 'Console', detail: c.text })
  }
  for (const c of collectorIssues.pageerrors) {
    report.issues.push({ severity: 'Critical', type: 'JS error', detail: c })
  }
  for (const h of collectorIssues.http) {
    report.issues.push({
      severity: severityOf('', h.status),
      type: `HTTP ${h.status}`,
      detail: `${h.method} ${h.url}`,
    })
  }
  for (const f of collectorIssues.failed) {
    if (isArtifact(f.error)) report.artifacts.push(`${f.url} — ${f.error}`)
    else report.issues.push({ severity: 'Medium', type: 'Сеть', detail: `${f.url} — ${f.error}` })
  }

  // --- клик-обход ---
  const order = [
    ...els.filter((e) => !DESTRUCTIVE_RE.test(e.name) && !LOGOUT_RE.test(e.name) && !SKIP_HREF.test(e.href)),
    ...els.filter((e) => DESTRUCTIVE_RE.test(e.name) && !LOGOUT_RE.test(e.name) && !SKIP_HREF.test(e.href)),
  ]
  const limit = opts.limit ?? 160
  for (const el of order.slice(0, limit)) {
    const before = page.url()
    const rec = { id: el.id, key: el.key, tag: el.tag, name: el.name, result: 'ok', note: '' }

    // После любой перезагрузки страницы data-audit-id обнуляются — ищем
    // элемент заново по устойчивому ключу (тег + имя + номер дубля).
    const fresh = await injectIds(page)
    let target = fresh.find((x) => x.key === el.key)
    if (!target) {
      // мягкий матч: тот же тег и имя, но другой номер дубля (состав списка
      // изменился после предыдущего действия — например, удалили строку)
      const base = el.key.replace(/#\d+$/, '')
      target = fresh.find((x) => x.key.replace(/#\d+$/, '') === base)
      if (target) {
        rec.result = 'ok'
        rec.note = 'мягкое совпадение (позиция в списке изменилась)'
      }
    }
    if (!target) {
      rec.result = 'skipped'
      rec.note = 'элемент исчез после предыдущего действия'
      report.clicks.push(rec)
      continue
    }
    const loc = page.locator(`[data-audit-id="${target.id}"]`)

    // Подводим элемент в зону клика; иначе elementFromPoint ниже fold вернёт
    // null и элемент будет ошибочно помечен «перекрытым».
    await loc.scrollIntoViewIfNeeded({ timeout: 2500 }).catch(() => {})

    const reach = await page
      .evaluate((id) => {
        const el = document.querySelector(`[data-audit-id="${id}"]`)
        if (!el) return { offscreen: true, covered: true }
        const r = el.getBoundingClientRect()
        // Скрытая раскладка (мобильный дубль) уезжает за горизонтальный край —
        // по вертикали элемент может быть просто ниже fold, это не дефект.
        const offscreen = r.right < 0 || r.left > window.innerWidth
        const cx = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 1)
        const cy = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 1)
        const top = document.elementFromPoint(cx, cy)
        const covered = !top || !(top === el || el.contains(top) || top.contains(el))
        return { offscreen, covered, rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } }
      }, target.id)
      .catch(() => ({ offscreen: false, covered: false }))

    if (reach.offscreen) {
      rec.result = 'skipped'
      rec.note = 'за пределами экрана (скрытая раскладка)'
      report.clicks.push(rec)
      continue
    }
    if (reach.covered) {
      rec.result = 'skipped'
      rec.note = 'перекрыт другим элементом'
      report.clicks.push(rec)
      continue
    }

    try {
      await loc.scrollIntoViewIfNeeded({ timeout: 2500 }).catch(() => {})
      await loc.click({ timeout: 4000, clickCount: 1 })
      await sleep(opts.delay ?? 350)
      const dlg = await visibleDialog(page)
      if (dlg) {
        rec.note = 'открылась модалка'
        await page.screenshot({ path: `${SHOTS}/dlg__${role}__${slug(url)}__${el.id}.png` }).catch(() => {})
        await closeDialog(page)
      }
      const after = page.url()
      if (after !== before) {
        rec.result = 'navigate'
        rec.note = `${before.replace(BASE, '')} → ${after.replace(BASE, '')}`
      }
      const errs = collectors.drain()
      for (const c of errs.console.filter((c) => c.type === 'error')) {
        if (isArtifact(c.text)) report.artifacts.push(`${el.name || el.tag}: ${c.text}`)
        else report.issues.push({ severity: 'High', type: 'Console', detail: `${el.name || el.tag}: ${c.text}` })
      }
      for (const c of errs.pageerrors) {
        report.issues.push({ severity: 'Critical', type: 'JS error', detail: `${el.name || el.tag}: ${c}` })
      }
      for (const h of errs.http) {
        report.issues.push({ severity: severityOf('', h.status), type: `HTTP ${h.status}`, detail: `${el.name || el.tag} → ${h.method} ${h.url}` })
      }
      for (const f of errs.failed) {
        if (isArtifact(f.error)) report.artifacts.push(`${el.name || el.tag}: ${f.url} — ${f.error}`)
        else report.issues.push({ severity: 'Medium', type: 'Сеть', detail: `${el.name || el.tag}: ${f.url} — ${f.error}` })
      }
    } catch (e) {
      rec.result = 'error'
      rec.note = String(e.message || e).split('\n')[0].slice(0, 160)
    }
    report.clicks.push(rec)
    // восстановление состояния страницы
    if (page.url() !== before || (await visibleDialog(page))) {
      await closeDialog(page)
      if (page.url() !== before) {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
        await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {})
        await sleep(300)
        await dismissCookieBanner(page)
      }
    }
    collectors.drain()
  }

  return report
}

/** Привести href из DOM к пути относительно BASE (BASE = .../price). */
function normalizeRoute(href) {
  if (!href) return null
  let h = href
  if (h.startsWith(BASE)) h = h.slice(BASE.length)
  if (!h.startsWith('/')) h = '/' + h
  if (h.startsWith('/price/')) h = h.slice('/price'.length)
  if (h === '/price') h = '/'
  return h.split('?')[0].split('#')[0]
}

/** Найти первую ссылку, подходящую под шаблон (для [id]-роутов). */
async function firstHref(page, listUrl, needle) {
  await page.goto(listUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})
  await sleep(600)
  const href = await page
    .locator(`a[href*="${needle}"]`)
    .first()
    .getAttribute('href')
    .catch(() => null)
  return normalizeRoute(href)
}

// ---------------------------------------------------------------- маршруты

const CLIENT_ROUTES = [
  '/dashboard',
  '/catalog',
  '/favorites',
  '/bulk-add',
  '/cart',
  '/checkout',
  '/orders',
  '/files',
  '/notifications',
  '/profile',
  '/profile/organization',
  '/profile/notifications',
  '/profile/sessions',
  '/consent',
]

const MANAGER_ROUTES = [
  '/manager',
  '/manager/catalog',
  '/manager/import',
  '/manager/brands',
  '/manager/banners',
  '/manager/news',
  '/manager/organizations',
  '/manager/users',
  '/manager/orders',
  '/manager/files',
  '/manager/currency',
  '/manager/audit',
  '/manager/admin',
  '/manager/analytics',
  '/manager/quotes',
  '/notifications',
  '/profile',
  '/profile/notifications',
  '/profile/sessions',
]

const PUBLIC_ROUTES = ['/', '/login', '/privacy', '/brands', '/news', '/reset-password']

const MOBILE_ROUTES = {
  client: ['/dashboard', '/catalog', '/cart', '/orders', '/notifications', '/profile', '/m', '/m/catalog', '/m/cart', '/m/orders', '/m/notifications'],
  manager: ['/manager', '/manager/catalog', '/manager/orders', '/manager/users'],
  public: ['/', '/login', '/brands'],
}

// ---------------------------------------------------------------- main

async function run() {
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
  const results = []

  const groups = ONLY === 'all' ? ['client', 'manager', 'public', 'mobile'] : [ONLY]

  for (const group of groups) {
    const ctx = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 },
      locale: 'ru-RU',
      timezoneId: 'Europe/Minsk',
    })
    const page = await ctx.newPage()
    // подтверждаем нативные диалоги — действие должно выполниться по-настоящему
    page.on('dialog', (d) => d.accept().catch(() => {}))

    if (group === 'client') {
      const u = await login(page, CLIENT)
      console.log('client login →', u)
      // клиент мог уйти на /consent
      if (page.url().includes('/consent')) {
        await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' })
      }
      const sku = await firstHref(page, `${BASE}/catalog`, '/catalog/')
      const order = await firstHref(page, `${BASE}/orders`, '/orders/')
      const routes = [...CLIENT_ROUTES]
      if (sku) routes.push(sku)
      if (order) routes.push(order)
      for (const r of routes) {
        console.log('→ client', r)
        results.push(await auditRoute(page, 'client', `${BASE}${r}`))
        writeFileSync(OUT, JSON.stringify(results, null, 2))
      }
    }

    if (group === 'manager') {
      const u = await login(page, MANAGER)
      console.log('manager login →', u)
      const uId = await firstHref(page, `${BASE}/manager/users`, '/manager/users/')
      const oId = await firstHref(page, `${BASE}/manager/orders`, '/manager/orders/')
      const orgId = await firstHref(page, `${BASE}/manager/organizations`, '/manager/organizations/')
      const routes = [...MANAGER_ROUTES]
      for (const d of [uId, oId, orgId]) if (d) routes.push(d)
      for (const r of routes) {
        console.log('→ manager', r)
        results.push(await auditRoute(page, 'manager', `${BASE}${r}`))
        writeFileSync(OUT, JSON.stringify(results, null, 2))
      }
    }

    if (group === 'extra') {
      // Целевая доливка: роль и маршруты задаются env (EXTRA_ROLE/EXTRA_ROUTES).
      const role = process.env.EXTRA_ROLE || 'manager'
      const routes = (process.env.EXTRA_ROUTES || '').split(',').map((s) => s.trim()).filter(Boolean)
      const email = process.env.EXTRA_EMAIL || (role === 'admin' ? 'admin.audit@priceweb.ru' : MANAGER.email)
      const password = process.env.EXTRA_PASSWORD || (role === 'admin' ? 'AdminAudit2026' : MANAGER.password)
      await login(page, { email, password })
      for (const r of routes) {
        console.log('→ extra', role, r)
        results.push(await auditRoute(page, `extra-${role}`, `${BASE}${r}`))
        writeFileSync(OUT, JSON.stringify(results, null, 2))
      }
    }

    if (group === 'public') {
      const routes = [...PUBLIC_ROUTES]
      const brand = await firstHref(page, `${BASE}/brands`, '/brands/')
      const news = await firstHref(page, `${BASE}/news`, '/news/')
      if (brand) routes.push(brand)
      if (news) routes.push(news)
      for (const r of routes) {
        console.log('→ public', r)
        results.push(await auditRoute(page, 'public', `${BASE}${r}`))
        writeFileSync(OUT, JSON.stringify(results, null, 2))
      }
    }

    if (group === 'mobile') {
      // мобильный проход: 390x844, проверка оверфлоу и бургер-меню
      const mctx = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
        locale: 'ru-RU',
      })
      const mp = await mctx.newPage()
      mp.on('dialog', (d) => d.accept().catch(() => {}))

      for (const [role, list] of Object.entries(MOBILE_ROUTES)) {
        if (role === 'client') await login(mp, CLIENT)
        if (role === 'manager') await login(mp, MANAGER)
        for (const r of list) {
          console.log('→ mobile', role, r)
          const rep = await auditRoute(mp, `mobile-${role}`, `${BASE}${r}`, { limit: 25, delay: 350 })
          const shot = `mobile__${role}__${slug(r)}.png`
          await mp.screenshot({ path: `${SHOTS}/${shot}` }).catch(() => {})
          rep.screenshots.push(shot)
          results.push(rep)
          writeFileSync(OUT, JSON.stringify(results, null, 2))
        }
      }
    }

    await ctx.close()
  }

  await browser.close()
  writeFileSync(OUT, JSON.stringify(results, null, 2))

  const total = results.reduce((n, r) => n + r.issues.length, 0)
  console.log(`\nГотово: ${results.length} страниц, ${total} замечаний`)
  for (const r of results) {
    if (r.issues.length) console.log(`  ${r.url.replace(BASE, '')} — ${r.issues.length}`)
  }
}

run().catch((e) => {
  console.error('FATAL', e)
  process.exit(1)
})
