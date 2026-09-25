<script setup lang="ts">
const route = useRoute()
const auth = useAuth()
const navSections = [
  {
    label: 'Работа',
    items: [
      { to: '/dashboard', label: 'Кабинет', icon: 'heroicons:building-office-2' },
      { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
      { to: '/cart', label: 'Текущая заявка', icon: 'heroicons:clipboard-document-list' },
      { to: '/orders', label: 'История заявок', icon: 'heroicons:clock' },
    ],
  },
  {
    label: 'Справочники',
    items: [
      { to: '/favorites', label: 'Избранное', icon: 'heroicons:heart' },
      { to: '/files', label: 'Документы', icon: 'heroicons:document-text' },
      { to: '/analytics', label: 'Аналитика', icon: 'heroicons:chart-bar' },
    ],
  },
]

function isActive(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <aside class="sticky top-24 hidden h-[calc(100dvh-7rem)] w-64 shrink-0 border-r border-border bg-surface lg:flex lg:flex-col" aria-label="Навигация кабинета">
    <div class="border-b border-border px-5 py-5">
      <div class="flex items-center gap-3">
        <span class="flex size-9 items-center justify-center bg-service text-service-ink" aria-hidden="true">
          <Icon name="heroicons:building-office-2" class="size-5" />
        </span>
        <div class="min-w-0">
          <p class="text-xs font-bold uppercase tracking-[0.14em] text-ink-muted">Клиентский кабинет</p>
          <p class="mt-1 truncate text-sm font-semibold text-ink">{{ auth.user?.company || auth.user?.name }}</p>
        </div>
      </div>
    </div>

    <nav class="flex-1 overflow-y-auto px-3 py-4" aria-label="Разделы кабинета">
      <div v-for="section in navSections" :key="section.label" class="mb-5 last:mb-0">
        <p class="mb-2 px-3 text-xs font-bold uppercase tracking-[0.16em] text-ink-muted">{{ section.label }}</p>
        <div class="space-y-1">
          <NuxtLink
            v-for="item in section.items"
            :key="item.to"
            :to="item.to"
            class="flex min-h-11 items-center gap-3 border-l-2 px-3 text-sm font-semibold transition-colors"
            :class="isActive(item.to) ? 'border-action bg-action-soft text-ink' : 'border-transparent text-ink-muted hover:bg-surface-2 hover:text-ink'"
            :aria-current="isActive(item.to) ? 'page' : undefined"
          >
            <Icon :name="item.icon" class="size-5 shrink-0" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </NuxtLink>
        </div>
      </div>
    </nav>
    <ManagerCard :manager="auth.user?.manager" />
  </aside>
</template>
