// middleware/m-auth.ts
// Защита роутов Telegram Mini App: неавторизованного пользователя
// всегда возвращаем на входную точку /m (§16 Mini App).
import { sessionMayBeRestored } from '~/utils/session'

export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  if (!auth.isAuthenticated && to.path !== '/m') {
    // Истёкший access-токен при живом refresh-токене: сессию восстановит
    // клиент (plugins/auth.session.ts), редирект на /m был бы лишним.
    if (sessionMayBeRestored()) return
    return navigateTo('/m')
  }
})
