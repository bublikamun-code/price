// ============================================================
//  Нагрузочный сценарий публичного каталога и лендинга.
//  Запуск:  BASE_URL=http://127.0.0.1:8081 k6 run infra/k6/catalog.js
//  (make test-load — просто обёртка над этой командой)
//
//  Сценарий отражает реальный трафик B2B-портала:
//    visitor — анонимный посетитель лендинга и каталога (кто и создаёт наплыв)
//    client  — залогиненный клиент: каталог, корзина, заявки
//
//  Токен клиента берётся из CLIENT_TOKEN (логин один раз на setup),
//  пароль в файле не хранится. Для анонимной части токен не нужен.
// ============================================================
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8081';
const TOKEN = __ENV.CLIENT_TOKEN || '';

// Куда смотреть при разборе: p95/p99 и доля ошибок важнее среднего.
const apiLatency = new Trend('api_latency', true);
const pageLatency = new Trend('page_latency', true);
const apiErrors = new Rate('api_errors');
const pageErrors = new Rate('page_errors');
const nonFive = new Counter('non_5xx_responses');

// Каталог на 1000 позиций — здесь берём реальные SKU, если каталог заполнен.
const SKUS = (__ENV.SKUS || '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

export const options = {
  scenarios: {
    visitor: {
      executor: 'ramping-vus',
      exec: 'visitor',
      startVUs: Number(__ENV.VUS_START || 10),
      stages: [
        { duration: __ENV.RAMP || '30s', target: Number(__ENV.VUS || 50) },
        { duration: __ENV.STEADY || '60s', target: Number(__ENV.VUS || 50) },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
    client: {
      executor: 'ramping-vus',
      exec: 'client',
      startVUs: Number(__ENV.VUS_START || 2),
      stages: [
        { duration: __ENV.RAMP || '30s', target: Number(__ENV.CLIENT_VUS || 10) },
        { duration: __ENV.STEADY || '60s', target: Number(__ENV.CLIENT_VUS || 10) },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    // Порогов, при которых «наплыв» считается провалом.
    // ВАЖНО: без тега {expected_response:...}. Кастомные метрики k6 его не
    // наследуют, и threshold по несуществующему тегу проходит наглухо —
    // тест выглядит зелёным, ничего не проверяя.
    'api_errors': ['rate<0.01'],
    'page_errors': ['rate<0.01'],
    'api_latency': ['p(95)<800', 'p(99)<2000'],
    'page_latency': ['p(95)<1500', 'p(99)<3000'],
    'http_req_failed': ['rate<0.01'],
  },
};

const jsonHeaders = (t) => ({
  'Content-Type': 'application/json',
  Accept: 'application/json',
  ...(t ? { Authorization: `Bearer ${t}` } : {}),
});

export function visitor() {
  // Анонимный посетитель: только SSR-лендинг. Каталог v2 закрыт авторизацией
  // (проверено: без токена /api/v2/catalog/products отдаёт 401), поэтому
  // анонимная часть намеренно не трогает API — иначе мы бы мерили 401,
  // а не реальную работу приложения.
  const page = http.get(`${BASE}/`, { tags: { name: 'landing' } });
  pageLatency.add(page.timings.duration);
  const pageOk = check(page, { 'лендинг 200': (r) => r.status === 200 });
  pageErrors.add(!pageOk);
  if (page.status !== 200) nonFive.add(1);

  sleep(Math.random() * 3 + 2); // человек читает, потом уходит или логинится
}

export function client() {
  if (!TOKEN) {
    // Без токена сценарий пользователя бессмыслен — но не валим прогон.
    sleep(1);
    return;
  }
  const cat = http.get(`${BASE}/api/v2/catalog/products?limit=24`, {
    headers: jsonHeaders(TOKEN),
    tags: { name: 'catalog' },
  });
  apiLatency.add(cat.timings.duration);
  const catOk = check(cat, { 'каталог 200': (r) => r.status === 200 });
  apiErrors.add(!catOk);
  if (cat.status !== 200) nonFive.add(1);

  // Фасеты — самая тяжёлая выборка (агрегаты по каталогу).
  const facets = http.get(`${BASE}/api/v2/catalog/facets`, {
    headers: jsonHeaders(TOKEN),
    tags: { name: 'facets' },
  });
  apiLatency.add(facets.timings.duration);
  const fOk = check(facets, { 'фасеты 200': (r) => r.status === 200 });
  apiErrors.add(!fOk);

  const cart = http.get(`${BASE}/api/v2/cart`, {
    headers: jsonHeaders(TOKEN),
    tags: { name: 'cart' },
  });
  apiLatency.add(cart.timings.duration);
  const cOk = check(cart, { 'корзина 200': (r) => r.status === 200 });
  apiErrors.add(!cOk);

  const orders = http.get(`${BASE}/api/v2/orders?limit=20`, {
    headers: jsonHeaders(TOKEN),
    tags: { name: 'orders' },
  });
  apiLatency.add(orders.timings.duration);
  const oOk = check(orders, { 'заявки 200': (r) => r.status === 200 });
  apiErrors.add(!oOk);

  if (SKUS.length) {
    const sku = SKUS[Math.floor(Math.random() * SKUS.length)];
    const p = http.get(`${BASE}/api/v2/catalog/products/by-sku/${encodeURIComponent(sku)}`, {
      headers: jsonHeaders(TOKEN),
      tags: { name: 'product' },
    });
    apiLatency.add(p.timings.duration);
    const pOk = check(p, { 'карточка 200': (r) => r.status === 200 });
    apiErrors.add(!pOk);
  }

  sleep(Math.random() * 3 + 2);
}

export function handleSummary(data) {
  const m = data.metrics;
  const line = (k) => {
    const x = m[k];
    return x ? `  ${k}: ${JSON.stringify(x.values)}` : `  ${k}: нет данных`;
  };
  return {
    stdout:
      `\n=== ИТОГИ ===\n` +
      `запросов: ${m.http_reqs ? m.http_reqs.values.count : '?'}\n` +
      `ошибок (checks): ${m.checks ? m.checks.values.passes : '?'} ok / ${m.checks ? m.checks.values.fails : '?'} fail\n` +
      `api_errors: ${m.api_errors ? (m.api_errors.values.rate * 100).toFixed(2) + '%' : '?'}\n` +
      `page_errors: ${m.page_errors ? (m.page_errors.values.rate * 100).toFixed(2) + '%' : '?'}\n` +
      line('http_req_duration') +
      '\n' +
      line('api_latency') +
      '\n' +
      line('page_latency') +
      `\n`,
  };
}
