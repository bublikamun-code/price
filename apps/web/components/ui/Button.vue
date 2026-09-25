<script setup lang="ts">
type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
type ButtonSize = 'compact' | 'default' | 'touch'

withDefaults(
  defineProps<{
    variant?: ButtonVariant
    size?: ButtonSize
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
  }>(),
  {
    variant: 'primary',
    size: 'default',
    type: 'button',
    disabled: false,
    loading: false,
  },
)

const variantClass: Record<ButtonVariant, string> = {
  primary: 'border-action bg-action text-action-on hover:bg-action-hover',
  secondary: 'border-border-strong bg-surface text-ink hover:bg-surface-2',
  outline: 'border-border bg-transparent text-ink hover:bg-surface-2',
  ghost: 'border-transparent bg-transparent text-ink hover:bg-surface-2',
  danger: 'border-danger bg-danger text-danger-on hover:bg-danger/90',
}
const sizeClass: Record<ButtonSize, string> = {
  compact: 'min-h-8 px-2.5 py-1 text-xs',
  default: 'min-h-9 px-3 py-1.5 text-sm',
  touch: 'min-h-11 px-4 py-2 text-sm',
}
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    class="inline-flex items-center justify-center gap-2 rounded-none border font-semibold transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-50"
    :class="[variantClass[variant], sizeClass[size]]"
  >
    <UiSpinner v-if="loading" :size="size === 'touch' ? 18 : 14" />
    <slot name="leading" />
    <slot />
    <slot name="trailing" />
  </button>
</template>
