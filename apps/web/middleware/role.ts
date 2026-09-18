// middleware/role.ts
// Защита роутов по ролям. Применяется через:
//   definePageMeta({ middleware: ['auth', 'role'], roles: ['MANAGER'] })
// Fail-closed: пустой/отсутствующий roles НЕ отключает проверку (иначе страница
// случайно открывается всем), а трактуется как «доступ запрещён».
export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  const roles = (to.meta.roles as string[] | undefined) ?? []

  // Неавторизованный → на /login (та же конвенция, что в middleware/auth.ts;
  // обычно раньше уже отработает 'auth' из пары ['auth', 'role']).
  if (!auth.user) {
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }

  // ADMIN «видит всё» — проходит любой role-гейт.
  if (roles.length > 0 && auth.user.role !== 'ADMIN' && !roles.includes(auth.user.role)) {
    throw createError({ statusCode: 403, statusMessage: 'Недостаточно прав' })
  }
})
