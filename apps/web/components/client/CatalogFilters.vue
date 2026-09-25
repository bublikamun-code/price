<script setup lang="ts">
import type {
  CatalogFacets,
  CatalogStockStatus,
} from '~/domain/api/v2/catalog.schema'

export interface CatalogFilterState {
  brands: string[]
  series: string[]
  stock: CatalogStockStatus | ''
  model: string
}

const FILTER_COLLAPSED = 6

const props = withDefaults(
  defineProps<{
    filters: CatalogFilterState
    facets: CatalogFacets
    modelOptions: Array<{ value: string; label: string }>
    /** Различает копии панели: у рельса и у шторки свои id и группы радиокнопок. */
    instance?: string
  }>(),
  { instance: 'rail' },
)

const emit = defineEmits<{
  'update:brands': [value: string[]]
  'update:series': [value: string[]]
  'update:stock': [value: CatalogStockStatus | '']
  'update:modelValue': [value: string]
  change: []
  reset: []
}>()

const brands = computed({
  get: () => props.filters.brands,
  set: (value: string[]) => emit('update:brands', value),
})
const seriesSelection = computed({
  get: () => props.filters.series,
  set: (value: string[]) => emit('update:series', value),
})
const stock = computed({
  get: () => props.filters.stock,
  set: (value: CatalogStockStatus | '') => emit('update:stock', value),
})
const modelValue = computed({
  get: () => props.filters.model,
  set: (value: string | number) => emit('update:modelValue', String(value)),
})

const modelId = computed(() => `catalog-model-${props.instance}`)
const stockName = computed(() => `catalog-stock-${props.instance}`)

const stockLabel: Record<CatalogStockStatus, string> = {
  IN_STOCK: 'В наличии',
  PREORDER: 'Под заказ',
}

const expanded = reactive<Record<string, boolean>>({})
const collapsed = reactive({ brands: false, series: false })

function visibleFilterItems<T extends { id: string }>(items: T[], key: string): T[] {
  return expanded[key] ? items : items.slice(0, FILTER_COLLAPSED)
}
function hiddenFilterCount<T extends { id: string }>(items: T[], key: string): number {
  return expanded[key] ? 0 : Math.max(0, items.length - FILTER_COLLAPSED)
}
function toggleGroup(key: keyof typeof collapsed) {
  collapsed[key] = !collapsed[key]
}
</script>

<template>
  <div class="px-4 pb-4">
    <div v-if="facets.brands.length" class="border-b border-border py-4">
      <button
        type="button"
        class="flex min-h-11 w-full items-center justify-between text-sm font-semibold text-ink"
        :aria-expanded="!collapsed.brands"
        @click="toggleGroup('brands')"
      >
        Производитель
        <span v-if="brands.length" class="numeric text-action">{{ brands.length }}</span>
        <Icon
          name="heroicons:chevron-down"
          class="size-4 text-ink-muted"
          :class="collapsed.brands ? '-rotate-90' : ''"
          aria-hidden="true"
        />
      </button>
      <div v-show="!collapsed.brands" class="space-y-1">
        <label
          v-for="brand in visibleFilterItems(facets.brands, 'brands')"
          :key="brand.id"
          class="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink"
        >
          <input v-model="brands" type="checkbox" :value="brand.id" class="size-4" @change="emit('change')">
          <span class="min-w-0 truncate">{{ brand.name }}</span>
        </label>
        <button
          v-if="hiddenFilterCount(facets.brands, 'brands')"
          type="button"
          class="min-h-11 text-xs font-semibold text-action hover:underline"
          @click="expanded.brands = true"
        >
          Показать все ({{ facets.brands.length }})
        </button>
      </div>
    </div>

    <div v-if="facets.series.length" class="border-b border-border py-4">
      <button
        type="button"
        class="flex min-h-11 w-full items-center justify-between text-sm font-semibold text-ink"
        :aria-expanded="!collapsed.series"
        @click="toggleGroup('series')"
      >
        Серия
        <span v-if="seriesSelection.length" class="numeric text-action">{{ seriesSelection.length }}</span>
        <Icon
          name="heroicons:chevron-down"
          class="size-4 text-ink-muted"
          :class="collapsed.series ? '-rotate-90' : ''"
          aria-hidden="true"
        />
      </button>
      <div v-show="!collapsed.series" class="max-h-52 space-y-1 overflow-y-auto">
        <label
          v-for="series in visibleFilterItems(facets.series, 'series')"
          :key="series.id"
          class="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink"
        >
          <input v-model="seriesSelection" type="checkbox" :value="series.id" class="size-4" @change="emit('change')">
          <span class="min-w-0 truncate">{{ series.name }}</span>
        </label>
        <button
          v-if="hiddenFilterCount(facets.series, 'series')"
          type="button"
          class="min-h-11 text-xs font-semibold text-action hover:underline"
          @click="expanded.series = true"
        >
          Показать все ({{ facets.series.length }})
        </button>
      </div>
    </div>

    <div class="border-b border-border py-4">
      <p class="mb-2 text-sm font-semibold text-ink">Наличие</p>
      <label class="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink">
        <input v-model="stock" type="radio" value="" :name="stockName" class="size-4" @change="emit('change')">
        Любое наличие
      </label>
      <label
        v-for="status in facets.stockStatuses"
        :key="status"
        class="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink"
      >
        <input v-model="stock" type="radio" :value="status" :name="stockName" class="size-4" @change="emit('change')">
        {{ stockLabel[status] }}
      </label>
    </div>

    <div class="py-4">
      <UiField :for="modelId" label="Модель">
        <UiSelect v-model="modelValue" :options="modelOptions" @update:model-value="emit('change')" />
      </UiField>
    </div>

    <button
      type="button"
      class="min-h-11 w-full border border-border text-sm font-semibold text-ink hover:bg-surface-2"
      @click="emit('reset')"
    >
      Сбросить фильтры
    </button>
  </div>
</template>
