// Обёртка над $api с автоматическим refresh-ом при 401.
// Использование: const { request } = useApi(); const data = await request<T>(url, opts)
import type { FetchOptions } from 'ofetch'

/** FetchOptions + внутренний флаг защиты от повторного retry при 401. */
interface FetchRetryOptions extends FetchOptions {
  _retried?: boolean
}

export function useApi() {
  const { $api } = useNuxtApp()
  const auth = useAuth()

  async function request<T>(url: string, opts: FetchOptions = {}): Promise<T> {
    try {
      return await ($api as unknown as <U>(u: string, o?: FetchOptions) => Promise<U>)(url, opts) as T
    } catch (e) {
      const retried = (opts as FetchRetryOptions)._retried
      if (getErrorStatus(e) === 401 && !retried) {
        const ok = await auth.refresh()
        if (ok) {
          ;(opts as FetchRetryOptions)._retried = true
          return await ($api as unknown as <U>(u: string, o?: FetchOptions) => Promise<U>)(url, opts) as T
        }
        auth.clear()
        if (import.meta.client) await navigateTo('/login')
      }
      throw e
    }
  }

  return { request, $api }
}
