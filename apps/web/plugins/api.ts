// Плагин API-клиента: ofetch-инстанс с авторизацией по cookie.
// baseURL: на сервере — внутренний (api:8000), на клиенте — публичный (localhost:8000).
// См. ARCHITECTURE_PLAN.md §6, §11.
import { csrfToken } from '~/utils/csrf'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const nuxtApp = useNuxtApp()
  const baseURL = import.meta.server ? config.apiBase : config.public.apiBase

  const api = $fetch.create({
    baseURL,
    credentials: 'include',
    // async: runWithContext при потерянном контексте возвращает Promise —
    // ждём его, чтобы Nuxt-контекст гарантированно сохранился.
    async onRequest({ options }) {
      const headers = new Headers(options.headers as HeadersInit)
      // В браузере HttpOnly-cookie отправляется автоматически. На SSR
      // внутренний $fetch не переносит входящие cookie, поэтому пробрасываем
      // Cookie и Bearer явно; это нужно и для refresh-cookie при 401.
      if (import.meta.server) {
        const requestHeaders = await nuxtApp.runWithContext(() => useRequestHeaders(['cookie']))
        const cookie = requestHeaders.cookie
        if (cookie) headers.set('Cookie', cookie)

        const token = await nuxtApp.runWithContext(() => useCookie<string | null>('access_token').value)
        if (token) headers.set('Authorization', `Bearer ${token}`)
      }

      const method = String(options.method ?? 'GET').toUpperCase()
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        // CSRF-токен читаем напрямую из cookie: useCookie вне scope компонента
        // создавал бы BroadcastChannel на каждый запрос (см. utils/csrf.ts).
        const token = csrfToken()
        if (token) headers.set('X-CSRF-Token', token)
      }
      options.headers = headers
    },
  })

  return {
    provide: { api },
  }
})
