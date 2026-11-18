// Восстановление сессии по refresh-токену.
//
// Access-токен живёт 15 минут (ACCESS_TOKEN_TTL_MIN), refresh-токен — 7 суток.
// Между ними есть окно, в котором access-кука браузера уже истекла, а сессия
// ещё жива: запрос уходит без access-токена и получает 401. Раньше клиент
// трактовал такой 401 как «сессии нет» и выкидывал пользователя на /login —
// пароль приходилось вводить каждые 15 минут, хотя refresh-токен был в порядке.
// Теперь 401 на /me означает «обновить access-токен», а не «выйти».
//
// Ключ useState, которым SSR делится с клиентом: флаг едет в payload и говорит
// клиенту — «сессию, возможно, ещё можно восстановить».
export const MAY_HAVE_SESSION_KEY = 'auth:may-have-session'

/**
 * Есть ли в текущем запросе refresh-кука.
 *
 * Только на сервере: HttpOnly-куку из JS не видно, на клиенте этот признак
 * недоступен. Само значение куки не читаем — нужен лишь факт наличия, и читать
 * его через useCookie нельзя: useCookie на SSR сериализует значение в payload,
 * то есть refresh-токен попал бы в HTML страницы.
 */
export function hasRefreshCookie(): boolean {
  if (!import.meta.server) return false
  try {
    const header = useRequestHeaders(['cookie']).cookie ?? ''
    return /(?:^|;\s*)refresh_token=/.test(header)
  } catch {
    // Вне request-контекста (например, в тестах) — считаем, что куки нет.
    return false
  }
}

/**
 * Сессию можно восстановить: refresh-кука пришла в запрос, значит access-токен
 * мог истёк, а сессия — нет. На клиенте всегда false: там решение принимает
 * плагин авторизации, а middleware срабатывает уже после его отработки.
 */
export function sessionMayBeRestored(): boolean {
  if (!import.meta.server) return false
  try {
    return useState<boolean>(MAY_HAVE_SESSION_KEY).value === true
  } catch {
    return false
  }
}
