<script setup lang="ts">
export interface SegmentOption {
  value: string
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: SegmentOption[]
    label: string
    disabled?: boolean
  }>(),
  { disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const uid = useId()

function select(value: string): void {
  emit('update:modelValue', value)
}

function onKeydown(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const enabled = props.options.filter((option) => !option.disabled)
  if (!enabled.length) return
  const currentIndex = enabled.findIndex((option) => option.value === props.modelValue)
  let nextIndex = currentIndex
  if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = enabled.length - 1
  else if (event.key === 'ArrowRight') nextIndex = (Math.max(currentIndex, 0) + 1) % enabled.length
  else nextIndex = (Math.max(currentIndex, 0) - 1 + enabled.length) % enabled.length
  const next = enabled[nextIndex]
  if (next) select(next.value)
  nextTick(() => document.getElementById(`${uid}-${next?.value}`)?.focus())
}
</script>

<template>
  <div
    role="radiogroup"
    :aria-label="label"
    class="inline-flex max-w-full items-stretch overflow-x-auto border border-border bg-surface p-0.5"
    @keydown="onKeydown"
  >
    <button
      v-for="option in options"
      :id="`${uid}-${option.value}`"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="modelValue === option.value"
      :tabindex="modelValue === option.value ? 0 : -1"
      :disabled="disabled || option.disabled"
      class="min-h-8 whitespace-nowrap px-3 py-1 text-sm font-semibold transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-50"
      :class="
        modelValue === option.value
          ? 'bg-service text-ink-on-service'
          : 'text-ink-muted hover:bg-surface-2 hover:text-ink'
      "
      @click="select(option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>
