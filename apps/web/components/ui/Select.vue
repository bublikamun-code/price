<script setup lang="ts">
const FIELD_IDS = Symbol.for('trade-field-ids')

export interface SelectChoice {
  value: string | number
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    options: SelectChoice[]
    label?: string
    placeholder?: string
    disabled?: boolean
    required?: boolean
    error?: string
    helperText?: string
  }>(),
  {
    modelValue: '',
    label: undefined,
    placeholder: 'Выберите значение',
    disabled: false,
    required: false,
    error: undefined,
    helperText: undefined,
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
const uid = useId()
const outer = inject<{
  controlId?: string
  labelId?: string
  descriptionId?: ComputedRef<string | undefined>
  errorId?: ComputedRef<string | undefined>
  invalid?: ComputedRef<boolean>
}>(FIELD_IDS, {})
const selectId = computed(() => outer.controlId || outer.labelId || `${uid}-label`)
const helperId = computed(() => (props.helperText || props.error ? `${uid}-helper` : undefined))
const invalid = computed(() => Boolean(props.error || outer.invalid?.value))
const describedBy = computed(
  () =>
    [outer.descriptionId?.value, outer.errorId?.value, helperId.value].filter(Boolean).join(' ') ||
    undefined,
)

function update(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const selected = props.options.find((option) => String(option.value) === value)
  if (selected) emit('update:modelValue', selected.value)
}
</script>

<template>
  <div class="min-w-0">
    <label v-if="label" :for="selectId" class="mb-1.5 block text-sm font-semibold text-ink">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true">*</span>
    </label>
    <div class="relative">
      <select
        :id="selectId"
        :value="modelValue"
        :disabled="disabled"
        :required="required"
        :aria-invalid="invalid || undefined"
        :aria-describedby="describedBy"
        :aria-labelledby="!label && outer.labelId ? outer.labelId : undefined"
        class="block min-h-11 w-full appearance-none rounded-none border bg-surface px-3 py-1.5 pr-9 text-sm text-ink focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-muted lg:min-h-9"
        :class="invalid ? 'border-danger' : 'border-border-strong'"
        @change="update"
      >
        <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
        <option
          v-for="option in options"
          :key="String(option.value)"
          :value="option.value"
          :disabled="option.disabled"
        >
          {{ option.label }}
        </option>
      </select>
      <Icon
        name="heroicons:chevron-down"
        class="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted"
        aria-hidden="true"
      />
    </div>
    <p
      v-if="helperText || error"
      :id="helperId"
      class="mt-1.5 text-xs leading-5"
      :class="error ? 'font-medium text-danger-text' : 'text-ink-muted'"
    >
      {{ error || helperText }}
    </p>
  </div>
</template>
