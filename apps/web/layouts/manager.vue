<script setup lang="ts">
// Layout менеджера: расширенный sidebar (управление).
// Навигация — см. SITEMAP.md §2.
// Приватная зона не индексируется (публичная SEO-витрина только на /brands).
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })
const route = useRoute()
const auth = useAuth()
const navItems = [
  { to: '/manager', label: 'Дашборд', icon: 'heroicons:chart-bar' },
  { to: '/manager/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/manager/import', label: 'Импорт прайса', icon: 'heroicons:arrow-up-tray' },
  { to: '/manager/brands', label: 'Бренды и серии', icon: 'heroicons:tag' },
  { to: '/manager/users', label: 'Клиенты', icon: 'heroicons:users' },
  { to: '/manager/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/manager/files', label: 'Файлы', icon: 'heroicons:folder' },
  { to: '/manager/banners', label: 'Баннеры', icon: 'heroicons:rectangle-stack' },
  { to: '/manager/news', label: 'Новости', icon: 'heroicons:newspaper' },
  { to: '/manager/currency', label: 'Курсы валют', icon: 'heroicons:banknotes' },
  { to: '/manager/audit', label: 'Аудит', icon: 'heroicons:shield-check' },
]
// Пункт только для роли ADMIN (§11 RBAC).
const adminNavItem = { to: '/manager/admin', label: 'Администрирование', icon: 'heroicons:shield-check' }

function isActive(to: string) {
  if (to === '/manager') return route.path === '/manager'
  return route.path.startsWith(to)
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <!-- Sidebar + контент в одном контейнере с шапкой (ровные границы) -->
    <div class="flex-1 flex justify-center">
      <div class="container-app flex">
        <aside class="hidden lg:flex flex-col w-64 shrink-0 border-r border-border bg-surface p-4 sticky top-[68px] h-[calc(100vh-68px)]">
          <p class="px-3 mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">Управление</p>
          <nav class="flex flex-col gap-1">
            <NuxtLink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              class="nav-link"
              :class="{ 'nav-link-active': isActive(item.to) }"
            >
              <Icon :name="item.icon" class="w-5 h-5" />
              <span>{{ item.label }}</span>
            </NuxtLink>
            <NuxtLink
              v-if="auth.isAdmin"
              :key="adminNavItem.to"
              :to="adminNavItem.to"
              class="nav-link"
              :class="{ 'nav-link-active': isActive(adminNavItem.to) }"
            >
              <Icon :name="adminNavItem.icon" class="w-5 h-5" />
              <span>{{ adminNavItem.label }}</span>
            </NuxtLink>
          </nav>
        </aside>

        <main class="flex-1 min-w-0 py-6 lg:py-8">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
