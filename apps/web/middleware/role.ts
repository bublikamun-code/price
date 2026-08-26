// middleware/role.ts
// Защита роутов по ролям. Применяется через:
//   definePageMeta({ middleware: ['auth', 'role'], roles: ['MANAGER'] })
export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  const roles = (to.meta.roles as string[] | undefined) ?? []
  if (roles.length === 0) return
  // ADMIN «видит всё» — проходит любой role-гейт.
  if (!auth.user || (auth.user.role !== 'ADMIN' && !roles.includes(auth.user.role))) {
    throw createError({ statusCode: 403, statusMessage: 'Недостаточно прав' })
  }
})
