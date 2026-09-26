// server/middleware/security-headers.ts — заголовки безопасности на HTML и статику.
//
// Прод собирается на PM2 за edge-nginx хостера (docs/PROD-h215691.md §Прод),
// конфига nginx в репозитории на сервере нет — поэтому единственное место, где
// браузер гарантированно получит эти заголовки, это само приложение.
//
// CSP enforcing, а не report-only. 'unsafe-inline' в script/style нужен Nuxt
// SSR: гидратация и payload лежат в инлайн-скрипте, nonce-вариант здесь
// потребовал бы проброса nonce в unhead и легко ломает оживление страницы.
// Реальный вектор XSS при этом закрыт валидацией NUXT_PUBLIC_METRIKA_ID в
// nuxt.config.ts. Шрифты приходят @import'ом с Google Fonts (assets/css/main.css),
// поэтому fonts.googleapis.com в style-src и fonts.gstatic.com в font-src
// обязательны — без них портал потеряет Manrope и IBM Plex Mono.

import type { H3Event } from 'h3'

const CSP = [
  "default-src 'self'",
  // Метрика подключается через innerHTML в nuxt.config.ts и грузит tag.js.
  "script-src 'self' 'unsafe-inline' https://mc.yandex.ru",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' data: https://fonts.gstatic.com",
  // Фото товаров приходят из внешнего хранилища, отсюда широкий img-src.
  "img-src 'self' data: blob: https:",
  "connect-src 'self' https://mc.yandex.ru",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ')

const PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), payment=(), usb=()'

// Сутки по умолчанию: сайт за edge-nginx хостера с auto-SSL, и годовой HSTS
// заблокировал бы быстрый откат, если сертификат протухнет.
const HSTS_DEFAULT_MAX_AGE = 86400

/**
 * max-age в секундах, из окружения в РАНТАЙМЕ — не из nuxt.config.
 *
 * Прод отдаёт заранее собранный .output под PM2, и process.env в nuxt.config
 * там запекается в момент сборки: переменная, добавленная на сервере позже,
 * не дала бы эффекта до новой сборки. Здесь же читается process.env самого
 * Nitro, поэтому одно и то же имя HSTS_MAX_AGE работает и в docker, и под
 * PM2 — и совпадает с переменной на стороне API. 0 = заголовок не слать
 * (аварийный откат политики), мусор в переменной = дефолт.
 */
function hstsMaxAge(): number | null {
  const raw = process.env.HSTS_MAX_AGE
  if (raw === undefined || raw.trim() === '') return HSTS_DEFAULT_MAX_AGE
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isSafeInteger(parsed) || parsed < 0) return HSTS_DEFAULT_MAX_AGE
  return parsed === 0 ? null : parsed
}

function isHttps(event: H3Event): boolean {
  const proto = getRequestHeader(event, 'x-forwarded-proto') ?? ''
  if (proto) {
    return proto.split(',')[0]!.trim().toLowerCase() === 'https'
  }
  const url = getRequestURL(event)
  return url.protocol === 'https:'
}

export default defineEventHandler((event) => {
  setResponseHeader(event, 'X-Content-Type-Options', 'nosniff')
  setResponseHeader(event, 'X-Frame-Options', 'DENY')
  setResponseHeader(event, 'Referrer-Policy', 'strict-origin-when-cross-origin')
  setResponseHeader(event, 'Permissions-Policy', PERMISSIONS_POLICY)
  setResponseHeader(event, 'Cross-Origin-Opener-Policy', 'same-origin')
  const maxAge = hstsMaxAge()
  if (maxAge !== null && isHttps(event)) {
    setResponseHeader(event, 'Strict-Transport-Security', `max-age=${maxAge}`)
  }
  setResponseHeader(event, 'Content-Security-Policy', CSP)
})
