<script setup lang="ts">
type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'action'

const props = withDefaults(defineProps<{ tone?: StatusTone; label: string; dot?: boolean }>(), {
  tone: 'neutral',
  dot: false,
})

const classes: Record<StatusTone, string> = {
  neutral: 'border-border-strong bg-surface-2 text-ink',
  info: 'border-info/50 bg-info-soft text-info',
  success: 'border-success/50 bg-success-soft text-success-text',
  warning: 'border-warning/50 bg-warning-soft text-warning-text',
  danger: 'border-danger/50 bg-danger-soft text-danger-text',
  action: 'border-action bg-action text-action-on',
}
const dotClasses: Record<StatusTone, string> = {
  neutral: 'bg-ink-muted',
  info: 'bg-info',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  action: 'bg-action-on',
}
</script>

<template>
  <span
    class="inline-flex max-w-full items-center gap-1.5 border px-2 py-0.5 text-xs font-semibold leading-5"
    :class="classes[props.tone]"
  >
    <span
      v-if="dot"
      class="size-1.5 shrink-0 rounded-full"
      :class="dotClasses[props.tone]"
      aria-hidden="true"
    />
    <span class="truncate">{{ label }}</span>
  </span>
</template>
