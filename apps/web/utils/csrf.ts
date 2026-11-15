// CSRF-токен double-submit: значение лежит в cookie `csrf_token`
// (намеренно не HttpOnly — его должен читать JS, чтобы отдать в заголовке).
//
// Читать его через useCookie() на каждый запрос нельзя: useCookie вне scope
// компонента создаёт BroadcastChannel на каждый вызов и закрывает его только
// в onScopeDispose, а scope в async-обработчике onRequest отсутствует —
// на каждый API-запрос оставался бы незакрытый канал и watcher. В браузере
// значение и так доступно из document.cookie, поэтому читаем его напрямую.
const CSRF_COOKIE = 'csrf_token'

function readCookie(name: string): string | null {
  if (!import.meta.client) return null
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${name}=([^;]*)`),
  )
  if (!match) return null
  try {
    return decodeURIComponent(match[1] ?? '')
  } catch {
    return match[1] ?? null
  }
}

/**
 * Текущее значение CSRF-токена (или null, если cookie ещё не установлена —
 * тогда сервер пропустит запрос: CSRF применяется к запросам с сессионной
 * cookie).
 */
export function csrfToken(): string | null {
  if (import.meta.client) return readCookie(CSRF_COOKIE)
  // На сервере cookie берём из входящего запроса.
  try {
    const header = useRequestHeaders(['cookie']).cookie ?? ''
    const match = header.match(new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]*)`))
    return match ? decodeURIComponent(match[1] ?? '') : null
  } catch {
    return null
  }
}
