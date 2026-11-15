// Синхронизация сессии: cookie ↔ Pinia-стор.
// useCookie создаётся в КОНТЕКСТЕ ПЛАГИНА (валидный Nuxt-контекст и на сервере,
// и на клиенте). Cookie-refs передаются в стор через registerCookies(), и стор
// пишет user-cookie напрямую в действиях — без гонки таймингов watcher'ов.
// Запуск плагина раньше route-middleware гарантирует hydrated-состояние стора.
import type { AuthCookiePayload } from '~/types/api'
import { cookieHasExtraFields, parseCookiePayload } from '~/utils/auth-cookie'
import { isSessionRejected } from '~/utils/errors'
import { hasRefreshCookie, MAY_HAVE_SESSION_KEY } from '~/utils/session'

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
 *
 * 401/403 на /me — это в первую очередь «access-токен истёк» (TTL 15 мин), а
 * не «сессии нет»: refresh-токен живёт 7 суток. Если обновление разрешено
 * (только на клиенте!), пробуем обновить access-токен и подтвердить сессию
 * заново — без ввода пароля.
 *
 * Возвращает true, если сессия подтверждена.
 */
async function confirmSession(
  auth: ReturnType<typeof useAuth>,
  opts: { allowRefresh?: boolean } = {},
): Promise<boolean> {
  try {
    await auth.fetchMe()
    return true
  } catch (e) {
    if (!isSessionRejected(e)) {
      auth.failClosed()
      return false
    }
  }

  // На сервере обновлять токен НЕЛЬЗЯ: refresh ротирует refresh-токен, а новую
  // куку мы не пробрасываем в браузер — refresh-кука пользователя станет
  // отозванной и следующая попытка обновить сессию провалится.
  if (opts.allowRefresh && (await auth.refresh())) {
    try {
      await auth.fetchMe()
      return true
    } catch {
      // refresh прошёл, но /me сессию не подтвердил — считаем её мёртвой.
    }
  }
  auth.clear()
  return false
}

export default defineNuxtPlugin(async () => {
  const auth = useAuth()

  const userC = useCookie<AuthCookiePayload | null>('auth_user', { ...COOKIE_OPTS, maxAge: USER_MAX_AGE })
  const accessC = useCookie<string | null>('access_token', { ...COOKIE_OPTS })
  const mayHaveSession = useState<boolean>(MAY_HAVE_SESSION_KEY, () => false)

  // В Pinia попадает только user-cookie. access_token остаётся HttpOnly и
  // читается плагином API только на сервере из входящего запроса.
  auth.registerCookies({ userC })

  // user-cookie не подписана: её может переписать любой скрипт в браузере, а
  // роль из неё питает middleware/role.ts. Поэтому на сервере источником истины
  // служит только /me по настоящей HttpOnly access-cookie, а сама cookie
  // становится кэшем, который applyUser перезаписывает серверными данными.
  if (import.meta.server) {
    auth.user = null
    // Refresh-кука пришла в запросе → сессия, возможно, ещё жива (access-токен
    // истёк, refresh нет). Флаг едет в payload: клиент обновит access-токен
    // сам, а SSR-редирект на /login не сработает (см. middleware/auth.ts).
    mayHaveSession.value = hasRefreshCookie()
    if (accessC.value) {
      await confirmSession(auth)
    }
    return
  }

  // В браузере HttpOnly-cookie не видна, поэтому стартуем от user-cookie, но
  // всё равно подтверждаем сессию запросом /me — он выполняется до
  // route-middleware, так что подделка не успевает дойти до проверки роли.
  //
  // Cookie хранит ТОЛЬКО id и роль (аудит L10): это признак «сессия, возможно,
  // есть», а не источник профиля. auth.user из неё НЕ заполняется — полный
  // профиль и роль для гейта приходят из /me (см. middleware/role.ts).
  const cookieIdentity = parseCookiePayload(userC.value)
  // Старый формат cookie содержал полный профиль (email, ФИО, компания).
  // Переписываем его минимальной формой — ПДн уходят из браузера.
  if (cookieIdentity && cookieHasExtraFields(userC.value)) {
    auth.persistCookieIdentity(cookieIdentity)
  }
  // Подтверждаем не только при наличии user-cookie: она живёт сутки, а
  // refresh-токен — неделю. Если user-cookie истекла, а refresh жив, сессия
  // восстанавливается через refresh (см. confirmSession).
  if (cookieIdentity || mayHaveSession.value) {
    await confirmSession(auth, { allowRefresh: true })
  }
})
