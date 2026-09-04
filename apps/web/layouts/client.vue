<script setup lang="ts">
// Layout авторизованного клиента: шапка + sidebar (desktop) + нижняя навигация (mobile) + контент.
// Навигация — см. SITEMAP.md §2.
// Приватная зона не индексируется (публичная SEO-витрина только на /brands).
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })
const route = useRoute()
const auth = useAuth()
const navItems = [
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/favorites', label: 'Избранное', icon: 'heroicons:star' },
  { to: '/bulk-add', label: 'Массовое добавление', icon: 'heroicons:plus-circle' },
  { to: '/orders', label: 'Мои заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/dashboard', label: 'Аналитика', icon: 'heroicons:chart-bar' },
  { to: '/files', label: 'Файлы', icon: 'heroicons:folder' },
  // Профиль остался только в меню аватара (справа сверху) — дубль в сайдбаре убран
]

// Нижняя навигация для мобильных (<lg) — 4 пункта, «Меню» ведёт на /dashboard.
const bottomNavItems = [
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/dashboard', label: 'Меню', icon: 'heroicons:bars-3' },
]

function isActive(to: string) {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <div class="flex-1 flex">
      <!-- Sidebar (desktop) -->
      <aside class="hidden lg:flex flex-col w-64 shrink-0 border-r border-border bg-surface p-4 sticky top-[72px] h-[calc(100vh-72px)]">
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
        </nav>
        <div class="mt-auto pt-4">
          <ManagerCard :manager="auth.user?.manager" />
        </div>
      </aside>

      <!-- Content -->
      <main class="flex-1 min-w-0">
        <div class="container-app py-6 lg:py-8 pb-16 lg:pb-0">
          <slot />
        </div>
      </main>
    </div>
    <AppFooter />
    <AppCartPopup />

    <!-- Нижняя навигация (mobile) -->
    <nav class="fixed bottom-0 left-0 right-0 bg-surface border-t border-border z-40 px-4 py-2 lg:hidden pb-[env(safe-area-inset-bottom)]">
      <div class="flex items-center justify-around">
        <NuxtLink
          v-for="item in bottomNavItems"
          :key="item.to"
          :to="item.to"
          class="flex flex-col items-center gap-0.5 p-1 text-xs font-medium transition-colors"
          :class="isActive(item.to) ? 'text-primary' : 'text-ink-muted hover:text-ink'"
        >
          <Icon :name="item.icon" class="w-5 h-5" />
          <span>{{ item.label }}</span>
        </NuxtLink>
      </div>
    </nav>
  </div>
</template>
