<script setup lang="ts">
withDefaults(defineProps<{ label?: string; inline?: boolean }>(), {
  label: 'Загрузка данных',
  inline: false,
})
</script>

<template>
  <div
    class="flex items-center text-sm text-ink-muted"
    :class="inline ? 'gap-2 py-1' : 'min-h-32 justify-center gap-3'"
    role="status"
    :aria-label="label"
  >
    <UiSpinner :size="inline ? 14 : 18" :label="label" />
    <span v-if="!inline">{{ label }}</span>
  </div>
</template>
