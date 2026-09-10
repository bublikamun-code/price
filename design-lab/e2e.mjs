/* E2E GUI-прогон всех кабинетов: гость, клиент, менеджер, админ.
   Запуск: node e2e.mjs  → PASS/FAIL по каждому шагу, скриншоты падений в e2e/. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '/Users/yaroslav/Documents/Price web/apps/web/node_modules/playwright/index.mjs';

const BASE = 'http://localhost:8081';
const OUT = '/Users/yaroslav/Documents/Price web/design-lab/e2e';
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const stamp = Date.now().toString(36);

async function step(page, name, fn, shot = true) {
  try {
    await fn();
    results.push(`PASS ${name}`);
    console.log(`PASS ${name}`);
  } catch (e) {
    results.push(`FAIL ${name} :: ${String(e.message).split('\n')[0]}`);
    console.log(`FAIL ${name} :: ${String(e.message).split('\n')[0]}`);
    if (shot) {
      try { await page.screenshot({ path: path.join(OUT, `fail-${name.replace(/[^\w-]/g, '_')}.png`) }); } catch {}
    }
  }
}

async function authCookies(ctx, email, pass) {
  const login = await ctx.request.post(`${BASE}/api/v1/auth/login`, {
    data: { email, password: pass },
  });
  if (!login.ok()) throw new Error(`login failed ${login.status()} for ${email}`);
  const tokens = await login.json();
  const me = await (await ctx.request.get(`${BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  })).json();
  const user = {
    id: me.id, email: me.email, name: me.full_name, role: me.role,
    displayCurrency: me.display_currency, company: me.company, phone: me.phone,
    totpEnabled: false, priceDigestEnabled: false, priceDigestSources: [],
    consent_accepted: true, discountPercent: me.discount_percent ?? 0,
    manager: me.manager ?? null, forcePasswordChange: me.force_password_change ?? false,
  };
  // Кука кодируется как в приложении (useAuth.persistCookie: encodeURIComponent),
  // иначе SSR читает имя в mojibake → hydration mismatch в AppHeader.
  await ctx.addCookies([
    { name: 'auth_token', value: tokens.access_token, domain: 'localhost', path: '/' },
    { name: 'auth_user', value: encodeURIComponent(JSON.stringify(user)), domain: 'localhost', path: '/' },
  ]);
}

const hideOverlays = () => {
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if ((cs.position === 'fixed' || cs.position === 'sticky') && el.offsetHeight < 200) {
      const t = el.textContent || '';
      if (/cookie/i.test(t) || el.tagName.toLowerCase().startsWith('nuxt-') || el.id?.startsWith('nuxt-dev')) el.style.display = 'none';
    }
  }
};

const browser = await chromium.launch();

// ============ ГОСТЬ ============
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.setDefaultTimeout(15000);
  const p = await ctx.newPage();

  await step(p, 'g1-landing-products', async () => {
    await p.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Товары из каталога').waitFor({ state: 'visible' });
    const n = await p.locator('.card').count();
    if (n < 5) throw new Error(`cards=${n}`);
  });

  await step(p, 'g2-catalog-guard-redirect', async () => {
    await p.goto(`${BASE}/catalog`, { waitUntil: 'domcontentloaded' });
    await p.waitForURL(/\/login/, { timeout: 8000 });
  });

  await step(p, 'g3-login-wrong-password', async () => {
    await p.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
    await p.getByRole('textbox', { name: 'Email' }).fill('glass-test@svetvdome.by');
    await p.getByRole('textbox', { name: 'Пароль' }).fill('wrong-pass-123');
    await p.getByRole('button', { name: 'Войти' }).click();
    await p.getByText(/неверн|Неверн|ошибк|Ошибка|не удалось|Не удалось/).first().waitFor({ state: 'visible', timeout: 8000 });
  });

  await step(p, 'g4-brands-page', async () => {
    await p.goto(`${BASE}/brands`, { waitUntil: 'domcontentloaded' });
    await p.locator('a[href="/brands/keaz"]').waitFor({ state: 'visible' });
  });

  await step(p, 'g5-brand-detail-products', async () => {
    await p.goto(`${BASE}/brands/keaz`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2000);
    const t = await p.evaluate(() => document.body.innerText);
    if (!/3798|OptiBox/i.test(t)) throw new Error('no products visible');
  });

  await step(p, 'g6-404-page', async () => {
    await p.goto(`${BASE}/no-such-page-xyz`, { waitUntil: 'domcontentloaded' });
    await p.getByText(/404|не найден|не существует/i).first().waitFor({ state: 'visible' });
  });

  await step(p, 'g7-api-cart-unauthorized', async () => {
    const r = await ctx.request.get(`${BASE}/api/v1/cart`);
    if (r.status() !== 401 && r.status() !== 403) throw new Error(`status=${r.status()}`);
  });

  await ctx.close();
}

// ============ КЛИЕНТ ============
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.setDefaultTimeout(15000);
  await authCookies(ctx, 'glass-test@svetvdome.by', 'AuditTest12345');
  const p = await ctx.newPage();

  await step(p, 'c1-client-home-dashboard', async () => {
    await p.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Последние заявки').waitFor({ state: 'visible' });
  });

  await step(p, 'c2-catalog-loads', async () => {
    await p.goto(`${BASE}/catalog`, { waitUntil: 'domcontentloaded' });
    await p.getByText('В корзину').first().waitFor({ state: 'visible' });
  });

  await step(p, 'c3-catalog-search', async () => {
    await p.getByPlaceholder('Артикул, наименование').fill('SMARTWATT');
    await p.keyboard.press('Enter');
    await p.waitForTimeout(1500);
    await p.getByText('В корзину').first().waitFor({ state: 'visible' });
    const t = await p.evaluate(() => document.body.innerText);
    if (!/SMARTWATT/.test(t)) throw new Error('no SMARTWATT in results');
  });

  await step(p, 'c4-catalog-brand-filter', async () => {
    await p.getByPlaceholder('Артикул, наименование').fill('');
    await p.keyboard.press('Enter');
    await p.waitForTimeout(1200);
    await p.getByRole('checkbox', { name: 'SmartWatt', exact: true }).check();
    await p.waitForTimeout(1500);
    await p.getByText('В корзину').first().waitFor({ state: 'visible' });
    await p.getByRole('checkbox', { name: 'SmartWatt', exact: true }).uncheck();
  });

  await step(p, 'c5-catalog-view-toggle', async () => {
    await p.locator('button[title="Список"]').click();
    await p.waitForTimeout(800);
    const rows = await p.locator('table tbody tr').count();
    if (rows < 1) throw new Error('table view empty');
    await p.locator('button[title="Плитка"]').click();
  });

  let productUrl = '';
  await step(p, 'c6-open-product-card', async () => {
    await p.waitForTimeout(1000);
    productUrl = await p.locator('a[href^="/catalog/"]').first().getAttribute('href');
    await p.locator('a[href^="/catalog/"]').first().click();
    await p.waitForURL(/\/catalog\//, { timeout: 8000 });
    await p.getByText(/В корзину|Цена по запросу/).first().waitFor({ state: 'visible' });
  });

  await step(p, 'c7-add-to-cart', async () => {
    await p.getByText('В корзину').first().click();
    await p.waitForTimeout(1200);
    await p.goto(`${BASE}/cart`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    if (/Корзина пуста|пуста/i.test(t)) throw new Error('cart empty after add');
  });

  await step(p, 'c8-favorite-product', async () => {
    await p.goto(`${BASE}${productUrl}`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const favLabel = (await p.getByRole('button', { name: /В избр/ }).first().innerText()).trim();
    if (!favLabel.includes('В избранном')) {
      await p.getByRole('button', { name: /В избранное/ }).first().click();
      await p.waitForTimeout(1000);
    }
    await p.goto(`${BASE}/favorites`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    if (/Пока ничего не сохранено|пусто/i.test(t)) throw new Error('favorites empty');
  });

  let totalBefore = '';
  await step(p, 'c9-cart-qty-change', async () => {
    await p.goto(`${BASE}/cart`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    // у товара может не быть прайса («Итого» останется 0,00) — проверяем смену количества
    const qtyText = () => p.evaluate(() => document.querySelector('span.w-9, span.sm\\:w-10')?.textContent?.trim() ?? '');
    const before = await qtyText();
    const plusBtn = p.locator('button.btn-outline:has(svg)').nth(1);
    await plusBtn.click();
    await p.waitForTimeout(1500);
    const after = await qtyText();
    if (before === after) throw new Error(`qty unchanged (${before})`);
  });

  await step(p, 'c10-checkout-create-order', async () => {
    await p.goto(`${BASE}/cart`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Оформить заявку').first().click();
    await p.waitForURL(/\/checkout/, { timeout: 8000 });
    await p.getByText('Доставка', { exact: true }).last().click();
    await p.getByPlaceholder(/Сертификат/).fill('E2E автотест: комментарий к заявке');
    await p.getByRole('button', { name: 'Отправить заявку' }).click();
    await p.waitForURL(/\/orders\//, { timeout: 10000 });
  });

  await step(p, 'c11-orders-list-has-order', async () => {
    await p.goto(`${BASE}/orders`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    if (!/Новая|В обработке|заявка/i.test(t)) throw new Error('no orders visible');
  });

  await step(p, 'c12-client-pages-load', async () => {
    for (const path of ['/dashboard', '/files', '/notifications', '/news']) {
      await p.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(900);
      const err = await p.evaluate(() => document.body.innerText.match(/Не удалось|Ошибка сервера/)?.[0]);
      if (err) throw new Error(`${path}: ${err}`);
    }
  });

  await step(p, 'c13-profile-pages-load', async () => {
    for (const path of ['/profile', '/profile/security', '/profile/sessions', '/profile/notifications']) {
      await p.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(800);
      const h = await p.locator('h1, h2').first().count();
      if (!h) throw new Error(`${path}: no heading`);
    }
  });

  await step(p, 'c14-logout-via-header', async () => {
    await p.goto(`${BASE}/profile`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1000);
    // аватар-триггер дропдауна в шапке (кнопка с кружком инициалов + шеврон)
    await p.locator('button:has(span[class*="rounded-pill"])').first().click();
    await p.getByText('Выйти').first().click();
    await p.waitForTimeout(1500);
    await p.goto(`${BASE}/catalog`, { waitUntil: 'domcontentloaded' });
    await p.waitForURL(/\/login/, { timeout: 8000 });
  });

  await ctx.close();
}

// ============ МЕНЕДЖЕР ============
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.setDefaultTimeout(15000);
  await authCookies(ctx, 'manager@example.by', 'manager12345');
  const p = await ctx.newPage();
  const testEmail = `e2e-${stamp}@svetvdome.by`;

  await step(p, 'm1-manager-dashboard', async () => {
    await p.goto(`${BASE}/manager`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Дашборд').first().waitFor({ state: 'visible' });
    const n = await p.locator('.card').count();
    if (n < 3) throw new Error(`cards=${n}`);
  });

  await step(p, 'm2-users-page-and-modal', async () => {
    await p.goto(`${BASE}/manager/users`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Создать клиента').first().waitFor({ state: 'visible' });
    await p.getByText('Создать клиента').first().click();
    await p.locator('#cu-email').waitFor({ state: 'visible' });
  });

  await step(p, 'm3-create-client', async () => {
    const responses = [];
    p.on('response', async (r) => {
      if (r.url().includes('/manager/users') && r.request().method() === 'POST') {
        responses.push(`${r.status()} ${await r.text().catch(() => '')}`);
      }
    });
    await p.locator('#cu-email').fill(testEmail);
    await p.locator('#cu-name').fill('E2E Тестовый');
    await p.locator('#cu-company').fill('E2E Company');
    await p.locator('#cu-phone').fill('+375291112233');
    const disc = p.locator('#cu-discount');
    if (await disc.count()) await disc.fill('5');
    await p.getByRole('button', { name: 'Создать', exact: true }).last().click();
    await p.waitForTimeout(3000);
    // после успеха в БД появится клиент, а UI покажет диалог с временным паролем
    const check = await ctx.request.get(`${BASE}/api/v1/manager/users?q=${encodeURIComponent(testEmail)}`);
    const created = (await check.json())?.data?.items?.some?.((u) => u.email === testEmail)
      ?? (await check.json())?.data?.some?.((u) => u.email === testEmail);
    if (!created) throw new Error(`client not created via UI; api=${responses.join(' | ') || 'no POST'}`);
  });

  await step(p, 'm4-temp-password-dialog-shown', async () => {
    const t = await p.evaluate(() => document.body.innerText);
    if (!/временн/i.test(t)) throw new Error('temp-password dialog not shown after create');
  });

  await step(p, 'm4b-created-client-in-list', async () => {
    await p.goto(`${BASE}/manager/users`, { waitUntil: 'domcontentloaded' });
    await p.getByPlaceholder('Поиск по имени, email, компании…').fill(testEmail);
    await p.keyboard.press('Enter');
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    if (!t.includes(testEmail)) throw new Error('created client not in list');
  });

  await step(p, 'm5-manager-pages-load', async () => {
    for (const path of ['/manager/catalog', '/manager/import', '/manager/orders', '/manager/brands', '/manager/files', '/manager/banners', '/manager/news', '/manager/currency', '/manager/audit']) {
      await p.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(900);
      const err = await p.evaluate(() => document.body.innerText.match(/Не удалось загрузить|Ошибка сервера/)?.[0]);
      if (err) throw new Error(`${path}: ${err}`);
    }
  });

  await step(p, 'm6-rbac-manager-cannot-admin', async () => {
    await p.goto(`${BASE}/manager/admin`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    if (/Администрирование/.test(t) && !/403|доступ/i.test(t)) throw new Error('admin page accessible to MANAGER');
  });

  await ctx.close();
}

// ============ АДМИН ============
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.setDefaultTimeout(15000);
  await authCookies(ctx, 'admin-test@svetvdome.by', 'manager12345');
  const p = await ctx.newPage();

  await step(p, 'a1-admin-page-loads', async () => {
    await p.goto(`${BASE}/manager/admin`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Администрирование').first().waitFor({ state: 'visible' });
  });

  await step(p, 'a2-admin-sees-users-nav', async () => {
    await p.goto(`${BASE}/manager`, { waitUntil: 'domcontentloaded' });
    await p.getByText('Администрирование').first().waitFor({ state: 'visible' });
  });

  await ctx.close();
}

// ============ ЮЗАБИЛИТИ ============
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.setDefaultTimeout(15000);
  const p = await ctx.newPage();

  await step(p, 'u1-cookie-banner-accept-persists', async () => {
    await p.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
    const banner = p.getByRole('button', { name: 'Принять' });
    await banner.waitFor({ state: 'visible' });
    await banner.click();
    await p.waitForTimeout(800);
    await p.reload({ waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const still = await p.getByRole('button', { name: 'Принять' }).count();
    if (still > 0) throw new Error('banner reappears after accept');
  });

  await step(p, 'u2-theme-toggle-persists', async () => {
    await p.evaluate(() => localStorage.setItem('nuxt-color-mode-v2', 'light'));
    await p.reload({ waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    const cls = await p.evaluate(() => document.documentElement.className);
    if (!/light/.test(cls)) throw new Error(`html class=${cls}`);
    await p.evaluate(() => localStorage.setItem('nuxt-color-mode-v2', 'dark'));
  });

  await ctx.close();
}

await browser.close();
console.log('\n===== SUMMARY =====');
console.log(`PASS: ${results.filter(r => r.startsWith('PASS')).length}, FAIL: ${results.filter(r => r.startsWith('FAIL')).length}`);
for (const r of results.filter(r => r.startsWith('FAIL'))) console.log(r);
fs.writeFileSync(path.join(OUT, 'results.txt'), results.join('\n'));
