// Синхронизация сессии: cookie ↔ Pinia-стор.
// useCookie создаётся В КОНТЕКСТЕ ПЛАГИНА (валидный Nuxt-контекст и на сервере,
// и на клиенте). Cookie-refs передаются в стор через registerCookies(), и стор
// пишет их напрямую в login/logout/… — без гонки таймингов watcher'ов.
// Запуск плагина раньше route-middleware гарантирует hydrated-состояние стора.
import type { AuthUser } from '~/composables/useAuth'

const TOKEN_MAX_AGE = 60 * 60 // 1 ч
const USER_MAX_AGE = 60 * 60 * 24 // 1 день
const COOKIE_OPTS = { sameSite: 'lax' as const, path: '/' }

export default defineNuxtPlugin(() => {
  const auth = useAuth()

  const tokenC = useCookie<string | null>('auth_token', { ...COOKIE_OPTS, maxAge: TOKEN_MAX_AGE })
  const userC = useCookie<AuthUser | null>('auth_user', { ...COOKIE_OPTS, maxAge: USER_MAX_AGE })

  // подключаем cookie-refs к стору (стор пишет их напрямую в действиях)
  auth.registerCookies({ tokenC, userC })

  // hydrate состояния из cookie (server: из запроса; client: из document.cookie)
  auth.token = tokenC.value ?? null
  auth.user = userC.value ?? null

  // на клиенте тихо обновляем профиль, если сессия есть (не блокируя UI)
  if (import.meta.client && auth.token && auth.user) {
    auth.fetchMe().catch(() => {})
  }
})
