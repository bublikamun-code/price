<script setup lang="ts">
withDefaults(
  defineProps<{
    caption?: string
    stickyHeader?: boolean
    compact?: boolean
    overflowLabel?: string
  }>(),
  {
    caption: undefined,
    stickyHeader: false,
    compact: false,
    overflowLabel: 'Горизонтальная прокрутка таблицы',
  },
)
</script>

<template>
  <div
    class="relative w-full overflow-x-auto border border-border bg-surface"
    role="region"
    :aria-label="overflowLabel"
    tabindex="0"
  >
    <table class="w-full border-collapse text-left text-[13px] leading-[18px]">
      <caption v-if="caption" class="sr-only">
        {{
          caption
        }}
      </caption>
      <thead :class="stickyHeader ? 'sticky top-0 z-10 bg-surface-2' : 'bg-surface-2'">
        <slot name="header" />
      </thead>
      <tbody>
        <slot />
      </tbody>
      <tfoot v-if="$slots.footer">
        <slot name="footer" />
      </tfoot>
    </table>
  </div>
</template>
