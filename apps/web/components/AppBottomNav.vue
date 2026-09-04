<script setup lang="ts">
// Нижняя навигация для мобильных (<lg) — «воздушная» плавающая карточка,
// как остальные блоки портала. Пункты передаёт layout (свой набор для
// каждого кабинета: клиент / менеджер).
export interface BottomNavItem {
  to: string
  label: string
  icon: string
}

const props = defineProps<{ items: BottomNavItem[] }>()

const route = useRoute()

function isActive(to: string): boolean {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}
</script>

<template>
  <nav class="fixed bottom-3 inset-x-3 z-40 lg:hidden pb-[env(safe-area-inset-bottom)]">
    <div class="rounded-[22px] border border-border bg-surface/95 backdrop-blur shadow-card-hover px-2 py-1.5">
      <div class="flex items-center justify-around">
        <NuxtLink
          v-for="item in props.items"
          :key="item.to"
          :to="item.to"
          class="flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-[16px] text-xs font-medium transition-colors"
          :class="isActive(item.to) ? 'text-primary bg-primary-soft' : 'text-ink-muted hover:text-ink'"
        >
          <Icon :name="item.icon" class="w-5 h-5" />
          <span>{{ item.label }}</span>
        </NuxtLink>
      </div>
    </div>
  </nav>
</template>
