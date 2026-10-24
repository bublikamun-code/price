<script setup lang="ts">
export interface BottomNavItem {
  to: string
  label: string
  icon: string
}

const props = defineProps<{ items: BottomNavItem[] }>()
const route = useRoute()

function isActive(to: string): boolean {
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <nav
    class="fixed bottom-0 inset-x-0 z-40 border-t border-border bg-surface lg:hidden"
    :style="{ paddingBottom: 'env(safe-area-inset-bottom)' }"
    aria-label="Мобильная навигация"
  >
    <div class="mx-auto grid max-w-lg" :style="{ gridTemplateColumns: `repeat(${props.items.length}, minmax(0, 1fr))` }">
      <NuxtLink
        v-for="item in props.items"
        :key="item.to"
        :to="item.to"
        class="flex h-16 flex-col items-center justify-center gap-1 border-t-2 px-1 text-[10px] font-semibold transition-colors"
        :class="isActive(item.to) ? 'border-accent bg-accent-soft text-accent' : 'border-transparent text-ink-muted hover:text-ink'"
      >
        <Icon :name="item.icon" class="h-5 w-5" />
        <span class="max-w-full truncate">{{ item.label }}</span>
      </NuxtLink>
    </div>
  </nav>
</template>
