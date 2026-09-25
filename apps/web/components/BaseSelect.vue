<script setup lang="ts">
// Кастомный выпадающий селект (единый стиль с .input).
// Рендер в потоке — БЕЗ портала/popper: popper-портал (reka-ui) давал моргание
// экрана и сдвиг контента при открытии (аудит UX 19.09, откат пилота shadcn-vue).
// Доступность: role=combobox/listbox/option, клавиатура (стрелки/Enter/Space/
// Escape/Home/End), aria-expanded + aria-activedescendant.
// Используется в фильтрах: /files, /catalog. См. SITEMAP.
export interface SelectOption {
  value: string | number
  label: string
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    options?: SelectOption[]
    placeholder?: string
    id?: string
  }>(),
  { options: () => [], modelValue: null, placeholder: '', id: undefined },
)

const emit = defineEmits<{
  (e: 'update:modelValue' | 'change', value: SelectOption['value']): void
}>()

const open = ref(false)
const containerRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const activeIndex = ref(-1)
const uid = useId()

const selectedLabel = computed(
  () => props.options.find((o) => o.value === props.modelValue)?.label ?? props.placeholder ?? '',
)

function openList() {
  const current = props.options.findIndex((o) => o.value === props.modelValue)
  activeIndex.value = current >= 0 ? current : 0
  open.value = true
}

function close(refocus = false) {
  open.value = false
  activeIndex.value = -1
  if (refocus) triggerRef.value?.focus()
}

function toggle() {
  if (open.value) close()
  else openList()
}

function select(option: SelectOption) {
  emit('update:modelValue', option.value)
  emit('change', option.value)
  close(true)
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
      event.preventDefault()
      openList()
    }
    return
  }
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      activeIndex.value = Math.min(activeIndex.value + 1, props.options.length - 1)
      break
    case 'ArrowUp':
      event.preventDefault()
      activeIndex.value = Math.max(activeIndex.value - 1, 0)
      break
    case 'Home':
      event.preventDefault()
      activeIndex.value = 0
      break
    case 'End':
      event.preventDefault()
      activeIndex.value = props.options.length - 1
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      if (activeIndex.value >= 0) select(props.options[activeIndex.value])
      break
    case 'Escape':
      event.preventDefault()
      close(true)
      break
    case 'Tab':
      close()
      break
  }
}

function onDocumentClick(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    close()
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="containerRef" class="relative" @keydown="onKeydown">
    <button
      :id="id"
      ref="triggerRef"
      type="button"
      class="input flex min-h-11 w-full items-center justify-between gap-2 pr-10 text-left"
      role="combobox"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :aria-controls="open ? `${uid}-listbox` : undefined"
      :aria-activedescendant="open && activeIndex >= 0 ? `${uid}-opt-${activeIndex}` : undefined"
      :aria-label="id ? undefined : (selectedLabel || placeholder || 'Выберите значение')"
      @click="toggle"
    >
      <span class="truncate">{{ selectedLabel }}</span>
      <Icon
        name="heroicons:chevron-down"
        class="absolute right-3.5 top-1/2 size-4 -translate-y-1/2 text-ink-muted transition-transform"
        :class="open ? 'rotate-180' : ''"
        aria-hidden="true"
      />
    </button>
    <ul
      v-if="open"
      :id="`${uid}-listbox`"
      class="absolute z-50 mt-1 max-h-60 w-full min-w-max overflow-auto border border-border-strong bg-surface p-1 shadow-overlay"
      role="listbox"
    >
      <li
        v-for="(o, i) in options"
        :id="`${uid}-opt-${i}`"
        :key="o.value"
        role="option"
        :aria-selected="modelValue === o.value"
        class="min-h-11 w-full cursor-pointer whitespace-nowrap border-l-2 px-3 py-2 text-left text-sm transition-colors"
        :class="[
          i === activeIndex ? 'bg-surface-2' : '',
          modelValue === o.value ? 'border-action bg-surface-2 font-semibold text-ink' : 'border-transparent text-ink',
        ]"
        @click="select(o)"
        @mousemove="activeIndex = i"
      >
        {{ o.label }}
      </li>
    </ul>
  </div>
</template>
