// Синхронизация сессии: cookie ↔ Pinia-стор.
// useCookie создаётся В КОНТЕКСТЕ ПЛАГИНА (валидный Nuxt-контекст и на сервере,
// и на клиенте). Cookie-refs передаются в стор через registerCookies(), и стор
// пишет user-cookie напрямую в действиях — без гонки таймингов watcher'ов.
// Запуск плагина раньше route-middleware гарантирует hydrated-состояние стора.
import type { AuthUser } from '~/composables/useAuth'
import { isSessionRejected } from '~/utils/errors'

const USER_MAX_AGE = 60 * 60 * 24 // 1 день
const COOKIE_OPTS = { sameSite: 'lax' as const, path: '/' }

/**
 * Подтверждает сессию запросом /me по настоящей HttpOnly access-cookie.
 *
 * Ошибку /me нельзя трактовать одинаково: 401/403 — сервер прямо отказал, и
 * cookie надо стереть, а вот недоступный API, 5xx или таймаут — это «не удалось
 * спросить». Стирать сессию во втором случае нельзя: одно мигание бэкенда
 * выкидывало бы живых пользователей навсегда. Тогда сбрасываем только
 * состояние (auth.failClosed) — гейт роли всё равно закрыт, потому что он
 * смотрит на стор, а не на cookie, — а как только API отвечает, сессия
 * подтвердится снова.
 */
async function confirmSession(auth: ReturnType<typeof useAuth>) {
  try {
    await auth.fetchMe()
  } catch (e) {
    if (isSessionRejected(e)) auth.clear()
    else auth.failClosed()
  }
}

export default defineNuxtPlugin(async () => {
  const auth = useAuth()

  const userC = useCookie<AuthUser | null>('auth_user', { ...COOKIE_OPTS, maxAge: USER_MAX_AGE })
  const accessC = useCookie<string | null>('access_token', { ...COOKIE_OPTS })

  // В Pinia попадает только user-cookie. access_token остаётся HttpOnly и
  // читается плагином API только на сервере из входящего запроса.
  auth.registerCookies({ userC })

  // user-cookie не подписана: её может переписать любой скрипт в браузере, а
  // роль из неё питает middleware/role.ts. Поэтому на сервере источником истины
  // служит только /me по настоящей HttpOnly access-cookie, а сама cookie
  // становится кэшем, который applyUser перезаписывает серверными данными.
  if (import.meta.server) {
    auth.user = null
    if (accessC.value) {
      await confirmSession(auth)
    }
    return
  }

  // В браузере HttpOnly-cookie не видна, поэтому стартуем от user-cookie, но
  // всё равно подтверждаем сессию запросом /me — он выполняется до
  // route-middleware, так что подделка не успевает дойти до проверки роли.
  auth.user = userC.value ?? null
  if (auth.user) {
    await confirmSession(auth)
  }
})
