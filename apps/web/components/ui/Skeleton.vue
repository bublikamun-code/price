<script setup lang="ts">
withDefaults(defineProps<{ width?: string; height?: string; label?: string }>(), {
  width: '100%',
  height: '1rem',
  label: 'Загрузка',
})
</script>

<template>
  <div
    class="rounded-none bg-surface-2"
    :style="{ width, height }"
    role="status"
    :aria-label="label"
    aria-hidden="true"
  />
</template>
