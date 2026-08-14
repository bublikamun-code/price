<script setup lang="ts">
// Layout авторизованного клиента: шапка + sidebar + контент.
// Навигация — см. SITEMAP.md §2.
const route = useRoute()
const navItems = [
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/favorites', label: 'Избранное', icon: 'heroicons:star' },
  { to: '/bulk-add', label: 'Массовое добавление', icon: 'heroicons:plus-circle' },
  { to: '/cart', label: 'Корзина', icon: 'heroicons:shopping-cart' },
  { to: '/orders', label: 'Мои заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/files', label: 'Файлы', icon: 'heroicons:folder' },
  { to: '/profile', label: 'Профиль', icon: 'heroicons:user' },
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
      <aside class="hidden lg:flex flex-col w-64 shrink-0 border-r border-border bg-surface p-4 sticky top-[64px] h-[calc(100vh-64px)]">
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
      </aside>

      <!-- Content -->
      <main class="flex-1 min-w-0">
        <div class="container-app py-6 lg:py-8">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
