// middleware/consent.global.ts
// Согласие на обработку ПДн: клиент без принятого согласия ведётся на /consent.
// Глобальное (запускается на каждой навигации, до страничных middleware).
//
// Защитные оговорки:
// - действует ТОЛЬКО на авторизованных клиентов (менеджеров не трогаем);
// - при user === null (SSR/первая навигация до hydrate) ничего не делаем —
//   логин-редирект и auth.session/fetchMe заполнят пользователя на клиенте;
// - строгое сравнение с false: у старой cookie поля нет (undefined) — не редиректим.
export default defineNuxtRouteMiddleware((to) => {
  const SKIP_PATHS = ['/consent', '/login', '/privacy']
  if (SKIP_PATHS.includes(to.path)) return
  // Mini App /m/** (§16 п.27): consent принимается в веб-кабинете,
  // повторно в Telegram webview не запрашивается.
  if (to.path === '/m' || to.path.startsWith('/m/')) return
  // Публичная SEO-витрина /brands** (§16 п.29): доступна гостям, consent-gate не применяется.
  if (to.path === '/brands' || to.path.startsWith('/brands/')) return

  const auth = useAuth()
  if (!auth.user) return
  if (auth.isAuthenticated && auth.isClient && auth.user.consent_accepted === false) {
    return navigateTo('/consent')
  }
})
