// server/middleware/security-headers.ts — заголовки безопасности на HTML и статику.
//
// Прод собирается на PM2 за edge-nginx хостера (docs/PROD-h215691.md §Прод),
// конфига nginx в репозитории на сервере нет — поэтому единственное место, где
// браузер гарантированно получит эти заголовки, это само приложение.
//
// CSP (DEC-02): в prod script-src без 'unsafe-inline' — вместо него
// per-request nonce. Middleware на каждом запросе генерирует nonce, кладёт его
// в event.context и шлёт CSP-заголовок; глобальный хук render:html (см. ниже)
// проставляет этот nonce в инлайн-<script>-теги SSR-разметки — гидратация и
// payload Nuxt, Метрика, color-mode все попадают в SSR HTML и накрываются
// инъекцией. Владелец CSP — только этот middleware: статическая копия в
// nginx.prod.conf убрана, т.к. политика с unsafe-inline пересекалась бы с
// nonce-политикой и блокировала бы все инлайн-скрипты (единый владелец — по
// образцу DEC-01: HSTS у nginx, CSP у приложения).
//
// 'unsafe-inline' в style-src сохранён намеренно: компоненты красятся
// динамическими :style-биндингами (style-атрибуты), а не инлайн-<style> —
// миграция на style-src-attr hashes осознанно отложена (§16 п.30(2)).
// Шрифты приходят @import'ом с Google Fonts (assets/css/main.css), поэтому
// fonts.googleapis.com в style-src и fonts.gstatic.com в font-src обязательны —
// без них портал потеряет Manrope и IBM Plex Mono.

import { randomBytes } from 'node:crypto'
import type { H3Event } from 'h3'

function csp(scriptSrc: string): string {
  return [
    "default-src 'self'",
    scriptSrc,
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
}

// Dev: nonce-политика несовместима с vite-режимом (HMR и клиентские вставки
// идут без nonce), поэтому здесь остаётся прежний статический CSP.
const CSP_DEV = csp("script-src 'self' 'unsafe-inline' https://mc.yandex.ru")

// Ключ в event.context, через который middleware передаёт nonce хуку
// render:html. Контекст живёт в рамках одного запроса — утечки между
// запросами нет.
const CONTEXT_KEY = '__cspNonce'

/**
 * Проставляет nonce инлайн-<script>-тегам (тегам без src — включая
 * type="application/json", это безвредно). Внешние скрипты с src авторизуются
 * в CSP по origin и атрибут не получают. Уже проставленный nonce не дублируем —
 * инъекция должна быть идемпотентной. Чистая функция без зависимости от Nitro —
 * покрывается юнит-тестами напрямую.
 */
export function injectScriptNonce(html: string, nonce: string): string {
  return html.replace(/<(script\b)([^>]*)>/gi, (tag, name: string, attrs: string) => {
    // (^|\s)src — иначе зацепим data-src; регэксп по паре атрибутов, а не по
    // полному разбору тега: Nuxt сам разметку не портил и здесь не начнёт.
    if (/(^|\s)src\s*=/i.test(attrs) || /(^|\s)nonce\s*=/i.test(attrs)) return tag
    return `<${name} nonce="${nonce}"${attrs}>`
  })
}

/** Поля контекста render:html на самом деле бывают и строкой, и массивом строк. */
type HtmlChunks = {
  head?: string[] | string
  body?: string[] | string
  bodyPrepend?: string[] | string
  bodyAppend?: string[] | string
}

// Хук обязан быть зарегистрирован один раз за жизнь процесса: server middleware
// выполняется на каждый запрос, и повторная регистрация копила бы обработчики.
let renderHookRegistered = false

function ensureRenderHook(): void {
  if (renderHookRegistered) return
  renderHookRegistered = true

  useNitroApp().hooks.hook('render:html', (html, { event }) => {
    const nonce = event.context[CONTEXT_KEY]
    if (typeof nonce !== 'string') return // dev или ответ без SSR-разметки

    const chunks = html as unknown as HtmlChunks
    for (const key of ['head', 'body', 'bodyPrepend', 'bodyAppend'] as const) {
      const chunk = chunks[key]
      if (Array.isArray(chunk)) {
        for (let i = 0; i < chunk.length; i++) {
          chunk[i] = injectScriptNonce(chunk[i]!, nonce)
        }
      } else if (typeof chunk === 'string') {
        chunks[key] = injectScriptNonce(chunk, nonce)
      }
    }
  })
}

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

  if (process.env.NODE_ENV === 'production') {
    ensureRenderHook()
    const nonce = randomBytes(16).toString('base64')
    event.context[CONTEXT_KEY] = nonce
    // telegram.org — внешний скрипт Telegram Web App (layouts/miniapp.vue).
    setResponseHeader(
      event,
      'Content-Security-Policy',
      csp(`script-src 'self' 'nonce-${nonce}' https://mc.yandex.ru https://telegram.org`),
    )
  } else {
    setResponseHeader(event, 'Content-Security-Policy', CSP_DEV)
  }
})
