<script setup lang="ts">
// Layout менеджера: расширенный sidebar (управление).
// Навигация — см. SITEMAP.md §2.
const route = useRoute()
const navItems = [
  { to: '/manager', label: 'Дашборд', icon: 'heroicons:chart-bar' },
  { to: '/manager/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/manager/import', label: 'Импорт прайса', icon: 'heroicons:arrow-up-tray' },
  { to: '/manager/brands', label: 'Бренды и серии', icon: 'heroicons:tag' },
  { to: '/manager/users', label: 'Клиенты', icon: 'heroicons:users' },
  { to: '/manager/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/manager/files', label: 'Файлы', icon: 'heroicons:folder' },
  { to: '/manager/currency', label: 'Курсы валют', icon: 'heroicons:banknotes' },
  { to: '/manager/audit', label: 'Аудит', icon: 'heroicons:shield-check' },
]

function isActive(to: string) {
  if (to === '/manager') return route.path === '/manager'
  return route.path.startsWith(to)
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <div class="flex-1 flex">
      <aside class="hidden lg:flex flex-col w-64 shrink-0 border-r border-border bg-surface p-4 sticky top-[64px] h-[calc(100vh-64px)]">
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
        </nav>
      </aside>

      <main class="flex-1 min-w-0">
        <div class="container-app py-6 lg:py-8">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
