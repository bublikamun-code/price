// Плагин API-клиента: ofetch-инстанс с инъекцией Bearer-токена.
// baseURL: на сервере — внутренний (api:8000), на клиенте — публичный (localhost:8000).
// См. ARCHITECTURE_PLAN.md §6, §11.
export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBase : config.public.apiBase

  const api = $fetch.create({
    baseURL,
    credentials: 'include',
    onRequest({ options }) {
      const token = useCookie<string | null>('auth_token').value
      if (token) {
        const headers = new Headers(options.headers as HeadersInit)
        headers.set('Authorization', `Bearer ${token}`)
        options.headers = headers
      }
    },
  })

  return {
    provide: { api },
  }
})
