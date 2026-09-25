<script setup lang="ts">
withDefaults(defineProps<{ size?: number; label?: string }>(), {
  size: 16,
  label: 'Загрузка',
})
</script>

<template>
  <span
    role="status"
    :aria-label="label"
    class="inline-block shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
</template>
