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

// HSTS отдаёт edge-nginx (nginx.prod.conf, max-age=31536000). Приложение по
// умолчанию не дублирует заголовок: два противоречивых Strict-Transport-Security
// в одном ответе — баг, а не защита (DEC-01, FIX_PLAN_2026-10-23). Включение
// через HSTS_MAX_AGE — только для деплоев, где Nitro торчит наружу без nginx.

/**
 * max-age в секундах, из окружения в РАНТАЙМЕ — не из nuxt.config.
 *
 * process.env в nuxt.config запекается в момент сборки: переменная, добавленная
 * на сервере позже, не дала бы эффекта до новой сборки. Здесь же читается
 * process.env самого Nitro, поэтому HSTS_MAX_AGE работает без пересборки и
 * совпадает с переменной на стороне API. Не задан / 0 / мусор = заголовок
 * не слать (владелец политики — edge-nginx).
 */
function hstsMaxAge(): number | null {
  const raw = process.env.HSTS_MAX_AGE
  if (raw === undefined || raw.trim() === '') return null
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return null
  return parsed
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
