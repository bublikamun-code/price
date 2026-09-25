<script setup lang="ts">
type SortDirection = 'asc' | 'desc'

const props = withDefaults(
  defineProps<{
    sortKey: string
    activeSort?: string | null
    direction?: SortDirection
    numeric?: boolean
    label?: string
  }>(),
  { activeSort: null, direction: 'asc', numeric: false, label: undefined },
)
const emit = defineEmits<{
  sort: [sortKey: string, direction: SortDirection]
}>()

const ariaSort = computed(() => {
  if (props.activeSort !== props.sortKey) return undefined
  return props.direction === 'asc' ? 'ascending' : 'descending'
})

function sort(): void {
  const nextDirection: SortDirection =
    props.activeSort === props.sortKey && props.direction === 'asc' ? 'desc' : 'asc'
  emit('sort', props.sortKey, nextDirection)
}
</script>

<template>
  <th
    scope="col"
    :aria-sort="ariaSort"
    :class="numeric ? 'text-right' : 'text-left'"
    class="border-b border-border-strong px-3 py-2 text-xs font-semibold text-ink-muted"
  >
    <button
      type="button"
      class="inline-flex min-h-8 items-center gap-1.5 font-semibold hover:text-ink"
      :class="numeric ? 'flex-row-reverse' : ''"
      :aria-label="`Сортировать по ${label || sortKey}`"
      @click="sort"
    >
      <slot>{{ label || sortKey }}</slot>
      <span class="text-[10px] leading-none" aria-hidden="true">
        {{ activeSort === sortKey ? (direction === 'asc' ? '▲' : '▼') : '↕' }}
      </span>
    </button>
  </th>
</template>
