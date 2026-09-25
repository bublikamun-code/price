<script setup lang="ts">
const FIELD_IDS = Symbol.for('trade-field-ids')

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    type?: string
    label?: string
    placeholder?: string
    disabled?: boolean
    readonly?: boolean
    required?: boolean
    error?: string
    helperText?: string
    monospace?: boolean
  }>(),
  {
    modelValue: '',
    type: 'text',
    label: undefined,
    placeholder: undefined,
    disabled: false,
    readonly: false,
    required: false,
    error: undefined,
    helperText: undefined,
    monospace: false,
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const uid = useId()
const outer = inject<{
  controlId?: string
  labelId?: string
  descriptionId?: ComputedRef<string | undefined>
  errorId?: ComputedRef<string | undefined>
  invalid?: ComputedRef<boolean>
}>(FIELD_IDS, {})
const inputId = computed(() => outer.controlId || outer.labelId || `${uid}-label`)
const helperId = computed(() => (props.helperText || props.error ? `${uid}-helper` : undefined))
const invalid = computed(() => Boolean(props.error || outer.invalid?.value))
const describedBy = computed(
  () =>
    [outer.descriptionId?.value, outer.errorId?.value, helperId.value].filter(Boolean).join(' ') ||
    undefined,
)
</script>

<template>
  <div class="min-w-0">
    <label v-if="label" :for="inputId" class="mb-1.5 block text-sm font-semibold text-ink">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true">*</span>
    </label>
    <div class="relative flex min-w-0 items-stretch">
      <span
        v-if="$slots.leading"
        class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-ink-muted"
      >
        <slot name="leading" />
      </span>
      <input
        :id="inputId"
        :value="modelValue"
        :type="type"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :required="required"
        :aria-invalid="invalid || undefined"
        :aria-describedby="describedBy"
        :aria-labelledby="!label && outer.labelId ? outer.labelId : undefined"
        class="block min-h-11 w-full rounded-none border bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-muted lg:min-h-9"
        :class="[
          invalid ? 'border-danger' : 'border-border-strong',
          $slots.leading ? 'pl-9' : '',
          $slots.trailing ? 'pr-9' : '',
          monospace ? 'numeric' : '',
        ]"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      >
      <span
        v-if="$slots.trailing"
        class="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-muted"
      >
        <slot name="trailing" />
      </span>
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
