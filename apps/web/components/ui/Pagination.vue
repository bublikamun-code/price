<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    page: number
    pageCount: number
    total?: number
    label?: string
    siblingCount?: number
  }>(),
  { total: undefined, label: 'Страницы результата', siblingCount: 1 },
)
const emit = defineEmits<{ 'update:page': [page: number] }>()

const safePageCount = computed(() => Math.max(1, props.pageCount))
const visiblePages = computed(() => {
  const last = safePageCount.value
  const current = Math.min(Math.max(props.page, 1), last)
  const first = Math.max(1, current - props.siblingCount)
  const end = Math.min(last, current + props.siblingCount)
  const values: number[] = []
  if (first > 1) values.push(1)
  if (first > 2) values.push(-1)
  for (let value = first; value <= end; value += 1) values.push(value)
  if (end < last - 1) values.push(-1)
  if (end < last) values.push(last)
  return values
})

function go(page: number): void {
  const next = Math.min(Math.max(page, 1), safePageCount.value)
  if (next !== props.page) emit('update:page', next)
}
</script>

<template>
  <nav class="flex min-h-11 flex-wrap items-center justify-between gap-2" :aria-label="label">
    <p v-if="total !== undefined" class="text-xs text-ink-muted" aria-live="polite">
      Всего: <span class="numeric font-semibold text-ink">{{ total }}</span>
    </p>
    <div class="flex items-center gap-1">
      <UiIconButton
        label="Предыдущая страница"
        size="touch"
        variant="ghost"
        :disabled="page <= 1"
        @click="go(page - 1)"
      >
        <Icon name="heroicons:chevron-left" class="size-4" aria-hidden="true" />
      </UiIconButton>
      <template v-for="(item, index) in visiblePages" :key="`${item}-${index}`">
        <span
          v-if="item < 0"
          class="flex size-9 items-center justify-center text-xs text-ink-muted"
          aria-hidden="true"
          >…</span
        >
        <button
          v-else
          type="button"
          class="numeric size-9 border text-xs font-semibold"
          :class="
            item === page
              ? 'border-action bg-action text-action-on'
              : 'border-border bg-surface text-ink hover:bg-surface-2'
          "
          :aria-current="item === page ? 'page' : undefined"
          :aria-label="`Страница ${item}`"
          @click="go(item)"
        >
          {{ item }}
        </button>
      </template>
      <UiIconButton
        label="Следующая страница"
        size="touch"
        variant="ghost"
        :disabled="page >= safePageCount"
        @click="go(page + 1)"
      >
        <Icon name="heroicons:chevron-right" class="size-4" aria-hidden="true" />
      </UiIconButton>
    </div>
  </nav>
</template>
