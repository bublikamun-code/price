// Обёртка над $api с автоматическим refresh-ом при 401.
// Использование: const { request } = useApi(); const data = await request<T>(url, opts)
import type { FetchOptions } from 'ofetch'

/** FetchOptions + внутренний флаг защиты от повторного retry при 401. */
interface FetchRetryOptions extends FetchOptions {
  _retried?: boolean
}

// ============================================================
// Single-flight refresh (аудит 2026-09-06, гонка параллельных 401).
// Модульный уровень → общий на ВСЕ экземпляры useApi в приложении:
// первый 401 запускает ровно один POST /auth/refresh, параллельные
// 401-запросы разделяют тот же promise и повторяют исходные запросы
// после его успеха. Без него N параллельных запросов шлют N refresh
// одним httpOnly-токеном, ротация одноразовая → часть получает 401.
//
// SSR-нюанс: на сервере модульное состояние общее для всех SSR-запросов
// разных пользователей — там single-flight не используется, refresh ходит
// напрямую через стор (per-request). На клиенте — общий promise.
// ============================================================
let sharedRefresh: Promise<boolean> | null = null
let loginRedirectInFlight = false

export function useApi() {
  const { $api, $router } = useNuxtApp()
  const auth = useAuth()

  /** Один общий refresh на все параллельные 401 (клиент); на сервере — прямой вызов. */
  function refreshOnce(): Promise<boolean> {
    if (import.meta.server) return auth.refresh()
    if (!sharedRefresh) {
      sharedRefresh = auth.refresh().finally(() => {
        sharedRefresh = null
      })
    }
    return sharedRefresh
  }

  async function request<T>(url: string, opts: FetchOptions = {}): Promise<T> {
    try {
      return await ($api as unknown as <U>(u: string, o?: FetchOptions) => Promise<U>)(url, opts) as T
    } catch (e) {
      const retried = (opts as FetchRetryOptions)._retried
      if (getErrorStatus(e) === 401 && !retried) {
        const ok = await refreshOnce()
        if (ok) {
          ;(opts as FetchRetryOptions)._retried = true
          return await ($api as unknown as <U>(u: string, o?: FetchOptions) => Promise<U>)(url, opts) as T
        }
        // Неудачный refresh → logout. clear() идемпотентен; редирект запускаем
        // ровно один (и только после окончательной неудачи single-flight refresh,
        // т.е. параллельные 401 дождутся его исхода), чтобы N неудачных запросов
        // не устроили N navigateTo.
        auth.clear()
        if (import.meta.client && !loginRedirectInFlight) {
          loginRedirectInFlight = true
          try {
            // Мини-апп живёт на /m/*: 401 там ведёт на вход мини-аппа /m,
            // а не на веб-/login. Проверка точная: /manager тоже начинается
            // с '/m', но это веб-кабинет менеджера.
            const path = $router.currentRoute.value.path
            const isMiniApp = path === '/m' || path.startsWith('/m/')
            await navigateTo(isMiniApp ? '/m' : '/login')
          } finally {
            loginRedirectInFlight = false
          }
        }
      }
      throw e
    }
  }

  return { request, $api }
}
