<script setup lang="ts">
// Кастомный выпадающий селект (единый стиль с .input).
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
  { options: () => [] },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: SelectOption['value']): void
  (e: 'change', value: SelectOption['value']): void
}>()

const open = ref(false)
const containerRef = ref<HTMLElement | null>(null)

const selectedLabel = computed(
  () => props.options.find((o) => o.value === props.modelValue)?.label ?? props.placeholder ?? '',
)

function select(option: SelectOption) {
  emit('update:modelValue', option.value)
  emit('change', option.value)
  open.value = false
}

function onDocumentClick(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div :id="id" ref="containerRef" class="relative">
    <button
      type="button"
      class="input w-full text-left flex items-center justify-between gap-2 pr-10"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="truncate">{{ selectedLabel }}</span>
      <Icon
        name="heroicons:chevron-down"
        class="w-4 h-4 text-ink-faint absolute right-3.5 top-1/2 -translate-y-1/2 transition-transform"
        :class="open ? 'rotate-180' : ''"
      />
    </button>
    <div
      v-if="open"
      class="absolute z-50 mt-1.5 w-full min-w-max bg-surface border border-border rounded-btn shadow-card-hover p-1.5 max-h-60 overflow-auto"
    >
      <button
        v-for="o in options"
        :key="o.value"
        type="button"
        class="w-full text-left px-3 py-2 rounded-btn text-sm transition-colors whitespace-nowrap"
        :class="modelValue === o.value ? 'bg-ink/5 text-ink font-semibold border-l-2 border-primary' : 'text-ink hover:bg-surface-2'"
        @click="select(o)"
      >
        {{ o.label }}
      </button>
    </div>
  </div>
</template>
