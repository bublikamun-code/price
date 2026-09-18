// Плагин API-клиента: ofetch-инстанс с инъекцией Bearer-токена.
// baseURL: на сервере — внутренний (api:8000), на клиенте — публичный (localhost:8000).
// См. ARCHITECTURE_PLAN.md §6, §11.
export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const nuxtApp = useNuxtApp()
  const baseURL = import.meta.server ? config.apiBase : config.public.apiBase

  const api = $fetch.create({
    baseURL,
    credentials: 'include',
    // async: runWithContext при потерянном контексте возвращает Promise —
    // ждём его, чтобы useCookie гарантированно выполнился в контексте Nuxt.
    async onRequest({ options }) {
      const headers = new Headers(options.headers as HeadersInit)
      // useCookie требует контекст Nuxt: при вложенных вызовах после await
      // (например, серии в brands/[slug]) он теряется — runWithContext его возвращает.
      const token = await nuxtApp.runWithContext(() => useCookie<string | null>('auth_token').value)
      if (token) headers.set('Authorization', `Bearer ${token}`)

      const method = String(options.method ?? 'GET').toUpperCase()
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const csrfToken = await nuxtApp.runWithContext(() => useCookie<string | null>('csrf_token').value)
        if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
      }
      options.headers = headers
    },
  })

  return {
    provide: { api },
  }
})
