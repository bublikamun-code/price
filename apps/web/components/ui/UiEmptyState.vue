<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    icon?: string
    compact?: boolean
  }>(),
  {
    description: undefined,
    icon: undefined,
    compact: false,
  },
)
</script>

<template>
  <div class="flex flex-col items-center px-4 text-center" :class="compact ? 'py-6' : 'py-10'">
    <div
      v-if="icon"
      class="mb-3 flex size-10 items-center justify-center border border-border bg-surface-2 text-ink-muted"
      aria-hidden="true"
    >
      <Icon :name="icon" class="size-5" />
    </div>
    <h3 class="text-base font-bold leading-5 text-ink">{{ title }}</h3>
    <p v-if="description" class="mt-1 max-w-md text-sm leading-5 text-ink-muted">
      {{ description }}
    </p>
    <div v-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>
