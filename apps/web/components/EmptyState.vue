<script setup lang="ts">
// Пустое состояние списков/таблиц: иконка, заголовок, описание, слот action.
defineProps<{
  icon: string
  title: string
  description?: string
}>()
</script>

<template>
  <div class="panel p-8 text-center">
    <div class="mx-auto mb-4 flex size-16 items-center justify-center border border-border bg-surface-2">
      <Icon :name="icon" class="w-8 h-8 text-ink-muted" />
    </div>
    <h3 class="text-base font-semibold mb-1">{{ title }}</h3>
    <p v-if="description" class="text-sm text-ink-muted mb-4 max-w-sm mx-auto">{{ description }}</p>
    <div v-if="$slots.action" class="flex justify-center">
      <slot name="action" />
    </div>
  </div>
</template>
