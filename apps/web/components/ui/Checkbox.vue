<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    label: string
    description?: string
    error?: string
    disabled?: boolean
    indeterminate?: boolean
    name?: string
    value?: string
  }>(),
  {
    modelValue: false,
    description: undefined,
    error: undefined,
    disabled: false,
    indeterminate: false,
    name: undefined,
    value: 'on',
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const uid = useId()
const input = ref<HTMLInputElement | null>(null)
const descriptionId = computed(() =>
  props.description || props.error ? `${uid}-description` : undefined,
)
const errorId = computed(() => (props.error ? `${uid}-error` : undefined))
const describedBy = computed(
  () => [descriptionId.value, errorId.value].filter(Boolean).join(' ') || undefined,
)

watch(
  () => props.indeterminate,
  (value) => {
    if (input.value) input.value.indeterminate = value
  },
  { immediate: true },
)
</script>

<template>
  <div class="min-w-0">
    <div class="relative flex min-h-11 items-start gap-2 lg:min-h-0">
      <span class="relative mt-0.5 flex size-5 shrink-0 items-center justify-center lg:mt-0">
        <input
          :id="`${uid}-checkbox`"
          ref="input"
          :name="name"
          :value="value"
          type="checkbox"
          :checked="modelValue"
          :disabled="disabled"
          :aria-invalid="Boolean(error) || undefined"
          :aria-describedby="describedBy"
          class="peer size-5 appearance-none rounded-none border border-border-strong bg-surface checked:border-action checked:bg-action indeterminate:border-action indeterminate:bg-action focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-50"
          @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
        >
        <Icon
          v-if="modelValue && !indeterminate"
          name="heroicons:check"
          class="pointer-events-none absolute size-3.5 text-action-on"
          aria-hidden="true"
        />
        <span
          v-else-if="indeterminate"
          class="pointer-events-none absolute h-0.5 w-2.5 bg-action-on"
          aria-hidden="true"
        />
      </span>
      <span aria-hidden="true" class="min-w-0 text-sm font-medium leading-5 text-ink">
        {{ label }}
      </span>
      <label
        :for="`${uid}-checkbox`"
        class="absolute inset-0"
        :class="disabled ? 'cursor-not-allowed' : 'cursor-pointer'"
      >
        <span class="sr-only">{{ label }}</span>
      </label>
    </div>
    <p v-if="description" :id="descriptionId" class="ml-7 mt-1 text-xs leading-5 text-ink-muted">
      {{ description }}
    </p>
    <p
      v-if="error"
      :id="errorId"
      role="alert"
      class="ml-7 mt-1 text-xs font-medium leading-5 text-danger-text"
    >
      {{ error }}
    </p>
  </div>
</template>
