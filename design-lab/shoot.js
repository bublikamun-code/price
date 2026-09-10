/* Съёмка скриншотов портала для сравнения дизайн-вариантов.
   Запуск: node shoot.js '<JSON список кадров>'
   Кадр: { name, page, theme, wait } — theme: dark|light, wait: текст готовности.
   На каждый кадр — свежий контекст: тема через addInitScript ДО старта приложения
   (@nuxtjs/color-mode перезаписывает storage при загрузке), куки — из одного логина. */
const path = require('path');
const { chromium } = require('/Users/yaroslav/Documents/Price web/apps/web/node_modules/playwright');

const BASE = 'http://localhost:8081';
const OUT = '/Users/yaroslav/Documents/Price web/design-lab';
const EMAIL = process.env.SHOOT_EMAIL || 'glass-test@svetvdome.by';
const PASS = process.env.SHOOT_PASS || 'AuditTest12345';

const mapUser = (m) => ({
  id: m.id, email: m.email, name: m.full_name, role: m.role,
  displayCurrency: m.display_currency, company: m.company, phone: m.phone,
  totpEnabled: m.totp_enabled ?? false,
  priceDigestEnabled: m.price_digest_enabled ?? false,
  priceDigestSources: m.price_digest_sources ?? [],
  consent_accepted: m.consent_accepted ?? true,
  discountPercent: m.discount_percent ?? 0,
  manager: m.manager ?? null,
  forcePasswordChange: m.force_password_change ?? false,
});

(async () => {
  const shots = JSON.parse(process.argv[2] || '[]');
  const browser = await chromium.launch();

  // один логин — куки переиспользуем во всех контекстах
  const boot = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const login = await boot.request.post(`${BASE}/api/v1/auth/login`, {
    data: { email: EMAIL, password: PASS },
  });
  if (!login.ok()) throw new Error(`login failed: ${login.status()}`);
  const tokens = await login.json();
  const me = await (await boot.request.get(`${BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  })).json();
  const cookies = [
    { name: 'auth_token', value: tokens.access_token, domain: 'localhost', path: '/' },
    { name: 'auth_user', value: JSON.stringify(mapUser(me)), domain: 'localhost', path: '/' },
  ];
  await boot.close();

  const hideCss = `nuxt-devtools-anchor, #nuxt-devtools-container, [id^="nuxt-devtools"] { display: none !important; }`;

  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript((t) => localStorage.setItem('nuxt-color-mode-v2', t), s.theme);
    await ctx.addCookies(cookies);
    const page = await ctx.newPage();
    await page.goto(`${BASE}${s.page}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
    let ready = false;
    const minCards = s.minCards ?? 4;
    for (let i = 0; i < 15; i++) {
      const n = await page.evaluate((re) => {
        const m = document.body.innerText.match(new RegExp(re));
        return m ? document.querySelectorAll('.card').length : 0;
      }, s.wait);
      if (n >= minCards) { ready = true; break; }
      await page.waitForTimeout(800);
    }
    if (!ready) throw new Error(`content not ready: ${s.name}`);
    await page.waitForTimeout(800);
    await page.addStyleTag({ content: hideCss });
    await page.evaluate(() => {
      for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if ((cs.position === 'fixed' || cs.position === 'sticky') && el.offsetHeight < 200) {
          const t = el.textContent || '';
          if (/cookie/i.test(t) || el.tagName.toLowerCase().startsWith('nuxt-') || el.id?.startsWith('nuxt-dev')) {
            el.style.display = 'none';
          }
        }
      }
    });
    await page.evaluate(() => {
      window.scrollTo(0, 60);
      document.body.getBoundingClientRect();
      window.scrollTo(0, 0);
      return document.fonts.ready;
    });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `${s.name}.png`) });
    console.log(`ok: ${s.name}`);
    await ctx.close();
  }
  await browser.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
