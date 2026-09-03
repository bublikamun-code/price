// middleware/m-auth.ts
// Защита роутов Telegram Mini App: неавторизованного пользователя
// всегда возвращаем на входную точку /m (§16 Mini App).
export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  if (!auth.isAuthenticated && to.path !== '/m') {
    return navigateTo('/m')
  }
})
