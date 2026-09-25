<script setup lang="ts">
const FIELD_IDS = Symbol.for('trade-field-ids')

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    placeholder?: string
    rows?: number
    disabled?: boolean
    readonly?: boolean
    required?: boolean
    error?: string
    helperText?: string
  }>(),
  {
    modelValue: '',
    label: undefined,
    placeholder: undefined,
    rows: 4,
    disabled: false,
    readonly: false,
    required: false,
    error: undefined,
    helperText: undefined,
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
const textareaId = computed(() => outer.controlId || outer.labelId || `${uid}-label`)
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
    <label v-if="label" :for="textareaId" class="mb-1.5 block text-sm font-semibold text-ink">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true">*</span>
    </label>
    <textarea
      :id="textareaId"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      :readonly="readonly"
      :required="required"
      :aria-invalid="invalid || undefined"
      :aria-describedby="describedBy"
      :aria-labelledby="!label && outer.labelId ? outer.labelId : undefined"
      class="block w-full resize-y rounded-none border bg-surface px-3 py-2 text-sm leading-5 text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-muted"
      :class="invalid ? 'border-danger' : 'border-border-strong'"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
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
