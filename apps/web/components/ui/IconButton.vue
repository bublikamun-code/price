<script setup lang="ts">
type IconButtonSize = 'compact' | 'default' | 'touch'
type IconButtonVariant = 'secondary' | 'outline' | 'ghost' | 'danger'

withDefaults(
  defineProps<{
    label: string
    size?: IconButtonSize
    variant?: IconButtonVariant
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
  }>(),
  {
    size: 'default',
    variant: 'outline',
    type: 'button',
    disabled: false,
    loading: false,
  },
)

const variantClass: Record<IconButtonVariant, string> = {
  secondary: 'border-border-strong bg-surface text-ink hover:bg-surface-2',
  outline: 'border-border bg-transparent text-ink hover:bg-surface-2',
  ghost: 'border-transparent bg-transparent text-ink-muted hover:bg-surface-2 hover:text-ink',
  danger: 'border-danger bg-transparent text-danger hover:bg-danger-soft',
}
const sizeClass: Record<IconButtonSize, string> = {
  compact: 'size-8',
  default: 'size-9',
  touch: 'size-11',
}
</script>

<template>
  <button
    :type="type"
    :aria-label="label"
    :title="label"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    class="inline-flex shrink-0 items-center justify-center border transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-50"
    :class="[
      variantClass[variant],
      sizeClass[size],
    ]"
  >
    <UiSpinner v-if="loading" :size="size === 'touch' ? 18 : 15" />
    <slot v-else />
  </button>
</template>
