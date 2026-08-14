// middleware/auth.ts
// Защита роутов, требующих авторизации.
// Применяется через definePageMeta({ middleware: 'auth' }) или глобально.
// Реальная проверка токена — на Этапе 2.
export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  if (!auth.isAuthenticated) {
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }
})
