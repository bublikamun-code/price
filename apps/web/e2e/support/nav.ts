import type { Page } from '@playwright/test'

/**
 * Базовый путь публикации приложения.
 *
 * Приложение собирается с `app.baseURL = NUXT_APP_BASE_URL` (см.
 * `apps/web/nuxt.config.ts`), и в штатной публикации это `/price`. Значит
 * браузер живёт по адресам `/price/…`, а не `/…`. Без этого знания набор
 * e2e не может стать зелёным на стенде: любые проверки абсолютного пути
 * (`/`, `/login`, `/privacy`) упираются в префикс.
 *
 * Значение берётся из окружения: `E2E_APP_BASE` — явный переопределитель
 * для прогона против другого стенда, `NUXT_APP_BASE_URL` — штатная
 * переменная проекта (в контейнере `web` она есть в `environment`).
 */
export const APP_BASE = (process.env.E2E_APP_BASE ?? process.env.NUXT_APP_BASE_URL ?? '')
  .trim()
  .replace(/\/+$/, '')

/**
 * Путь приложения с учётом базового префикса публикации.
 *
 * `appPath('/privacy')` → `/price/privacy`, `appPath('/')` → `/price/`
 * (слеш обязателен: именно так нормализует адрес браузер).
 * Для публикации в корень (`APP_BASE` пустой) поведение прежнее.
 */
export function appPath(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`
  if (!APP_BASE) return suffix
  return suffix === '/' ? `${APP_BASE}/` : `${APP_BASE}${suffix}`
}

/**
 * Регулярка для пути приложения с базовым префиксом публикации.
 *
 * `appPathRegExp('brands', 'catalog')` → `^/price/(brands|catalog)$`
 * (а для публикации в корень — `^/(brands|catalog)$`, как раньше).
 */
export function appPathRegExp(...segments: string[]): RegExp {
  const escape = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const base = escape(appPath('/'))
  const tail = segments.map(escape).join('|')
  return new RegExp(`^${base}(${tail})$`)
}

/**
 * `baseURL` для Playwright: адрес стенда + базовый префикс приложения.
 *
 * Если в `E2E_BASE_URL` префикс уже есть (например `https://host/price`),
 * второй раз его не добавляем.
 */
export function resolveBaseURL(raw?: string): string {
  const base = (raw ?? 'http://localhost:8081').trim().replace(/\/+$/, '')
  if (!APP_BASE) return base
  return base.endsWith(APP_BASE) ? base : `${base}${APP_BASE}`
}

/**
 * Переход по странице с `waitUntil: 'domcontentloaded'`.
 *
 * Playwright по умолчанию ждёт `load` — то есть пока не подгрузятся ВСЕ
 * подресурсы, включая внешние шрифты с fonts.googleapis.com и SSE-поток
 * уведомлений. На стенде без устойчивого внешнего интернета (или при
 * подвисании стороннего CDN) это превращается в 60-секундный таймаут
 * на пустом месте: страница уже отрисована, а `load` так и не наступил.
 *
 * `domcontentloaded` + ожидания через `expect` дают тот же результат:
 * проверки всё равно авто-дожидаются нужных элементов, но не зависят от
 * сторонних ресурсов.
 */
export async function goto(page: Page, path: string): Promise<void> {
  // Именно appPath, а не path: Playwright резолвит путь, начинающийся с '/',
  // от корня origin и базовый префикс (`/price`) при этом теряется.
  await page.goto(appPath(path), { waitUntil: 'domcontentloaded' })
}