<script setup lang="ts">
const FIELD_IDS = Symbol.for('trade-field-ids')

const props = withDefaults(
  defineProps<{
    for: string
    label: string
    description?: string
    error?: string
    required?: boolean
    labelHidden?: boolean
  }>(),
  {
    description: undefined,
    error: undefined,
    required: false,
    labelHidden: false,
  },
)

const uid = useId()
const descriptionId = computed(() =>
  props.description || props.error ? `${uid}-description` : undefined,
)
const errorId = computed(() => (props.error ? `${uid}-error` : undefined))
provide(FIELD_IDS, {
  controlId: props.for,
  labelId: `${uid}-label`,
  descriptionId,
  errorId,
  invalid: computed(() => Boolean(props.error)),
})
</script>

<template>
  <div class="min-w-0">
    <label
      :id="`${uid}-label`"
      :for="props.for"
      class="mb-1.5 block text-sm font-semibold text-ink"
      :class="labelHidden ? 'sr-only' : ''"
    >
      {{ label }}
      <span v-if="required" class="text-danger" aria-hidden="true">*</span>
      <span v-if="required" class="sr-only"> (обязательное поле)</span>
    </label>
    <p v-if="description" :id="descriptionId" class="mb-1.5 text-xs leading-5 text-ink-muted">
      {{ description }}
    </p>
    <slot :described-by="[descriptionId, errorId].filter(Boolean).join(' ') || undefined" />
    <p
      v-if="error"
      :id="errorId"
      role="alert"
      class="mt-1.5 text-xs font-medium leading-5 text-danger-text"
    >
      {{ error }}
    </p>
  </div>
</template>
