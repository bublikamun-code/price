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
const controlId = computed(() => outer.controlId || `${uid}-control`)
const listboxId = computed(() => `${uid}-listbox`)
const helperId = computed(() => (props.helperText || props.error ? `${uid}-helper` : undefined))
const invalid = computed(() => Boolean(props.error || outer.invalid?.value))
const describedBy = computed(
  () =>
    [outer.descriptionId?.value, outer.errorId?.value, helperId.value].filter(Boolean).join(' ') ||
    undefined,
)

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)

const selectableIndexes = computed(() =>
  props.options.reduce<number[]>((acc, option, index) => {
    if (!option.disabled) acc.push(index)
    return acc
  }, []),
)
const selectedIndex = computed(() =>
  props.options.findIndex((option) => String(option.value) === String(props.modelValue)),
)
const selected = computed(() => (selectedIndex.value >= 0 ? props.options[selectedIndex.value] : undefined))
const showPlaceholder = computed(() => !selected.value)
const activeOptionId = computed(() =>
  open.value && activeIndex.value >= 0 ? optionId(activeIndex.value) : undefined,
)

function optionId(index: number): string {
  return `${uid}-option-${index}`
}

function openList(startAt: 'first' | 'last' | 'selected' = 'first'): void {
  if (props.disabled || props.options.length === 0) return
  open.value = true
  if (startAt === 'selected' && selectedIndex.value >= 0) activeIndex.value = selectedIndex.value
  else if (startAt === 'last') {
    activeIndex.value = selectableIndexes.value[selectableIndexes.value.length - 1] ?? -1
  } else activeIndex.value = selectableIndexes.value[0] ?? -1
}

function close(): void {
  if (!open.value) return
  open.value = false
  activeIndex.value = -1
}

function toggle(): void {
  if (open.value) close()
  else openList('selected')
}

function choose(option: SelectChoice | undefined): void {
  if (!option || option.disabled) return
  emit('update:modelValue', option.value)
  close()
  trigger.value?.focus()
}

function move(offset: 1 | -1): void {
  const list = selectableIndexes.value
  if (!list.length) return
  const position = list.indexOf(activeIndex.value)
  const next =
    position === -1
      ? offset === 1
        ? 0
        : list.length - 1
      : (position + offset + list.length) % list.length
  activeIndex.value = list[next]
}

function onKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      if (!open.value) openList('selected')
      else move(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      if (!open.value) openList('last')
      else move(-1)
      break
    case 'Home':
      if (!open.value) {
        event.preventDefault()
        openList('first')
      }
      break
    case 'End':
      if (!open.value) {
        event.preventDefault()
        openList('last')
      }
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      if (open.value) choose(props.options[activeIndex.value])
      else openList('selected')
      break
    case 'Escape':
      event.preventDefault()
      close()
      break
    case 'Tab':
      close()
      break
    default:
      break
  }
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

watch(
  () => props.disabled,
  (value) => {
    if (value) close()
  },
)

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))
onUnmounted(() => document.removeEventListener('pointerdown', onDocumentPointerDown))
</script>

<template>
  <div ref="root" class="min-w-0">
    <label v-if="label" :for="controlId" class="mb-1.5 block text-sm font-semibold text-ink">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true">*</span>
    </label>
    <div class="relative">
      <button
        :id="controlId"
        ref="trigger"
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        :aria-expanded="open"
        :aria-controls="listboxId"
        :aria-activedescendant="activeOptionId"
        :aria-invalid="invalid || undefined"
        :aria-describedby="describedBy"
        :aria-labelledby="!label && outer.labelId ? outer.labelId : undefined"
        :disabled="disabled"
        class="flex min-h-11 w-full items-center justify-between gap-2 border bg-surface px-3 py-1.5 text-left text-sm focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-muted lg:min-h-9"
        :class="[
          invalid ? 'border-danger' : 'border-border-strong',
          showPlaceholder ? 'text-ink-muted' : 'text-ink',
          open ? 'border-focus ring-1 ring-focus' : '',
        ]"
        @click="toggle"
        @keydown="onKeydown"
      >
        <span class="min-w-0 truncate">{{ selected?.label ?? placeholder }}</span>
        <Icon
          name="heroicons:chevron-down"
          class="size-4 shrink-0 text-ink-muted transition-transform"
          :class="open ? 'rotate-180' : ''"
          aria-hidden="true"
        />
      </button>
      <div
        v-if="open"
        :id="listboxId"
        role="listbox"
        :aria-labelledby="!label && outer.labelId ? outer.labelId : undefined"
        class="absolute z-50 mt-1 max-h-64 w-full min-w-max overflow-y-auto border border-border-strong bg-surface p-1 shadow-overlay"
      >
        <div
          v-for="(option, index) in options"
          :id="optionId(index)"
          :key="String(option.value)"
          role="option"
          :aria-selected="index === selectedIndex"
          :aria-disabled="option.disabled || undefined"
          class="flex min-h-11 cursor-pointer items-center justify-between gap-3 px-3 py-1.5 text-sm lg:min-h-9"
          :class="[
            option.disabled ? 'text-ink-muted opacity-60' : 'text-ink',
            index === selectedIndex ? 'font-semibold' : 'font-medium',
            index === activeIndex ? 'bg-surface-2' : '',
          ]"
          @mouseenter="activeIndex = option.disabled ? activeIndex : index"
          @click="choose(option)"
        >
          <span class="min-w-0 truncate">{{ option.label }}</span>
          <Icon
            v-if="index === selectedIndex"
            name="heroicons:check"
            class="size-4 shrink-0 text-action"
            aria-hidden="true"
          />
        </div>
      </div>
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
