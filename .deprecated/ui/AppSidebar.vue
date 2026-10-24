<script setup lang="ts">
const route = useRoute()
const auth = useAuth()
const SIDEBAR_KEY = 'pp.sidebar.collapsed'
const collapsed = ref(false)

onMounted(() => {
  collapsed.value = localStorage.getItem(SIDEBAR_KEY) === '1'
})

function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem(SIDEBAR_KEY, collapsed.value ? '1' : '0')
}

const navItems = [
  { to: '/dashboard', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/favorites', label: 'Избранное', icon: 'heroicons:star' },
  { to: '/bulk-add', label: 'Массовое добавление', icon: 'heroicons:plus-circle' },
  { to: '/orders', label: 'Мои заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/analytics', label: 'Аналитика', icon: 'heroicons:chart-bar' },
  { to: '/files', label: 'Файлы', icon: 'heroicons:folder' },
]

function isActive(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <aside class="hidden lg:block shrink-0 sticky top-[76px] self-start py-5 pr-4" aria-label="Основная навигация">
    <div class="border border-border bg-surface transition-[width] duration-150" :class="collapsed ? 'w-14' : 'w-60'">
      <button
        class="w-full flex items-center border-b border-border py-2 px-2 text-ink-faint hover:text-ink"
        :class="collapsed ? 'justify-center' : 'justify-end'"
        :title="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
        :aria-label="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
        @click="toggleSidebar"
      >
        <Icon :name="collapsed ? 'heroicons:chevron-right' : 'heroicons:chevron-left'" class="w-4 h-4" />
      </button>
      <nav class="flex flex-col p-1" :class="collapsed ? 'items-center' : ''">
        <NuxtLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex min-h-10 items-center gap-3 border-l-2 px-3 text-sm font-medium transition-colors"
          :class="[
            collapsed ? 'w-10 justify-center px-0' : '',
            isActive(item.to)
              ? 'border-accent bg-accent-soft text-accent'
              : 'border-transparent text-ink-muted hover:bg-surface-2 hover:text-ink',
          ]"
          :title="collapsed ? item.label : undefined"
        >
          <Icon :name="item.icon" class="w-5 h-5 shrink-0" />
          <span v-if="!collapsed">{{ item.label }}</span>
        </NuxtLink>
      </nav>
      <div v-if="!collapsed" class="border-t border-border p-2">
        <ManagerCard :manager="auth.user?.manager" />
      </div>
    </div>
  </aside>
</template>
