// Синхронизация сессии: cookie ↔ Pinia-стор.
// useCookie создаётся В КОНТЕКСТЕ ПЛАГИНА (валидный Nuxt-контекст и на сервере,
// и на клиенте). Cookie-refs передаются в стор через registerCookies(), и стор
// пишет user-cookie напрямую в действиях — без гонки таймингов watcher'ов.
// Запуск плагина раньше route-middleware гарантирует hydrated-состояние стора.
import type { AuthUser } from '~/composables/useAuth'

const USER_MAX_AGE = 60 * 60 * 24 // 1 день
const COOKIE_OPTS = { sameSite: 'lax' as const, path: '/' }

export default defineNuxtPlugin(async () => {
  const auth = useAuth()

  const userC = useCookie<AuthUser | null>('auth_user', { ...COOKIE_OPTS, maxAge: USER_MAX_AGE })
  const accessC = useCookie<string | null>('access_token', { ...COOKIE_OPTS })

  // В Pinia попадает только user-cookie. access_token остаётся HttpOnly и
  // читается плагином API только на сервере из входящего запроса.
  auth.registerCookies({ userC })
  // На SSR доступ к access-cookie есть у Nuxt, поэтому не пропускаем stale
  // user-cookie в защищённый маршрут, если access-cookie уже исчезла.
  // В браузере HttpOnly-cookie не видна, поэтому там ориентируемся на
  // user-cookie и подтверждаем его запросом /me.
  auth.user = import.meta.server
    ? (accessC.value ? (userC.value ?? null) : null)
    : (userC.value ?? null)

  // После F5 HttpOnly-cookie не видна браузерному JS. Если user-cookie есть,
  // подтверждаем сессию запросом /me: браузер сам отправит access_token.
  if (import.meta.client && auth.user) {
    await auth.fetchMe().catch(() => auth.clear())
  }

  // Если user-cookie потерялась, но access-cookie ещё существует, серверный
  // запрос /me восстановит профиль до route-middleware. В браузере этот путь
  // недоступен, поэтому клиентский plugin выше оставляет гостя до входа.
  if (import.meta.server && accessC.value && !auth.user) {
    await auth.fetchMe().catch(() => auth.clear())
  }
})
