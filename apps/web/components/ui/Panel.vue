<script setup lang="ts">
withDefaults(
  defineProps<{
    as?: 'section' | 'article' | 'aside' | 'div'
    padded?: boolean
    elevated?: boolean
  }>(),
  { as: 'section', padded: false, elevated: false },
)
</script>

<template>
  <component
    :is="as"
    class="rounded-surface border border-border bg-surface"
    :class="[padded ? 'p-4' : '', elevated ? 'shadow-overlay' : '']"
  >
    <slot />
  </component>
</template>
