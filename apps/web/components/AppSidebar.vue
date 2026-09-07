<script setup lang="ts">
// Боковое меню клиента (desktop): карточка, как остальные блоки портала.
// Сворачивается до иконок (активный пункт — квадрат), состояние запоминается.
// Используется в layout client.vue и на дашборде главной (pages/index.vue).
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
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/favorites', label: 'Избранное', icon: 'heroicons:star' },
  { to: '/bulk-add', label: 'Массовое добавление', icon: 'heroicons:plus-circle' },
  { to: '/orders', label: 'Мои заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/dashboard', label: 'Аналитика', icon: 'heroicons:chart-bar' },
  { to: '/files', label: 'Файлы', icon: 'heroicons:folder' },
  // Профиль остался только в меню аватара (справа сверху) — дубль в сайдбаре убран
]

function isActive(to: string) {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}
</script>

<template>
  <aside class="hidden lg:block shrink-0 sticky top-[72px] self-start py-4 pr-4">
    <div
      class="glass p-3 transition-[width] duration-200"
      :class="collapsed ? 'w-[60px]' : 'w-60'"
    >
      <button
        class="btn-ghost p-2 mb-2 w-full flex"
        :class="collapsed ? 'justify-center' : 'justify-end'"
        :title="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
        :aria-label="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
        @click="toggleSidebar"
      >
        <Icon :name="collapsed ? 'heroicons:chevron-right' : 'heroicons:chevron-left'" class="w-4 h-4" />
      </button>
      <nav class="flex flex-col gap-1" :class="collapsed ? 'items-center' : ''">
        <NuxtLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="[
            collapsed ? 'w-10 h-10 justify-center px-0 py-0 shrink-0' : '',
            isActive(item.to) ? 'nav-link-active' : '',
          ]"
          :title="collapsed ? item.label : ''"
        >
          <Icon :name="item.icon" class="w-5 h-5 shrink-0" />
          <span v-if="!collapsed">{{ item.label }}</span>
        </NuxtLink>
      </nav>
      <div v-if="!collapsed" class="mt-3">
        <ManagerCard :manager="auth.user?.manager" />
      </div>
    </div>
  </aside>
</template>
