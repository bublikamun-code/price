// middleware/auth.ts
// Защита роутов, требующих авторизации.
// Применяется через definePageMeta({ middleware: 'auth' }) или глобально.
// Реальная проверка токена — на Этапе 2.
import { sessionMayBeRestored } from '~/utils/session'

export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  if (auth.isAuthenticated) return
  // SSR: access-токен мог истёк (TTL 15 мин), а refresh-токен (7 суток) — нет.
  // Ранний redirect выкинул бы живого пользователя на /login, и пароль пришлось
  // бы вводить каждые 15 минут. Вместо этого отдаём страницу как гостю: клиент
  // восстановит сессию через refresh (см. plugins/auth.session.ts) и догрузит
  // данные. На клиенте признак недоступен (refresh-кука HttpOnly) — там решение
  // уже принял плагин, и middleware срабатывает после его отработки.
  if (sessionMayBeRestored()) return
  return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
})
