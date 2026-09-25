<script setup lang="ts">
export interface RadioOption {
  value: string | number
  label: string
  description?: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    options: RadioOption[]
    label: string
    description?: string
    error?: string
    disabled?: boolean
    orientation?: 'vertical' | 'horizontal'
    name?: string
  }>(),
  {
    modelValue: '',
    description: undefined,
    error: undefined,
    disabled: false,
    orientation: 'vertical',
    name: undefined,
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
const uid = useId()
const name = computed(() => props.name || `${uid}-radio-group`)
const descriptionId = computed(() =>
  props.description || props.error ? `${uid}-description` : undefined,
)
const errorId = computed(() => (props.error ? `${uid}-error` : undefined))
const describedBy = computed(
  () => [descriptionId.value, errorId.value].filter(Boolean).join(' ') || undefined,
)
</script>

<template>
  <fieldset
    :aria-describedby="describedBy"
    :aria-invalid="Boolean(error) || undefined"
    class="min-w-0"
  >
    <legend class="mb-1.5 text-sm font-semibold text-ink">{{ label }}</legend>
    <p v-if="description" :id="descriptionId" class="mb-2 text-xs leading-5 text-ink-muted">
      {{ description }}
    </p>
    <div :class="orientation === 'horizontal' ? 'flex flex-wrap gap-x-5 gap-y-2' : 'space-y-2'">
      <label
        v-for="(option, index) in options"
        :key="String(option.value)"
        class="flex min-h-11 items-start gap-2 text-sm font-medium text-ink sm:min-h-0"
      >
        <span class="relative mt-0.5 flex size-5 shrink-0 items-center justify-center">
          <input
            :id="`${uid}-${index}`"
            :name="name"
            :value="option.value"
            type="radio"
            :checked="modelValue === option.value"
            :disabled="disabled || option.disabled"
            :aria-describedby="
              option.description ? `${uid}-option-${index}-description` : undefined
            "
            class="peer size-5 appearance-none rounded-full border border-border-strong bg-surface checked:border-[6px] checked:border-action focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50"
            @change="emit('update:modelValue', option.value)"
          >
        </span>
        <span>
          <span class="block leading-5">{{ option.label }}</span>
          <span
            v-if="option.description"
            :id="`${uid}-option-${index}-description`"
            class="block text-xs leading-5 text-ink-muted"
          >
            {{ option.description }}
          </span>
        </span>
      </label>
    </div>
    <p
      v-if="error"
      :id="errorId"
      role="alert"
      class="mt-1.5 text-xs font-medium leading-5 text-danger-text"
    >
      {{ error }}
    </p>
  </fieldset>
</template>
