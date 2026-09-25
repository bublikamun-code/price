<script setup lang="ts">
const props = defineProps<{
  productsCount?: number
  brandsCount?: number
  seriesCount?: number
}>()

const formatter = new Intl.NumberFormat('ru-RU')
const metrics = computed(() =>
  [
    { value: props.brandsCount, label: 'Брендов в каталоге' },
    { value: props.seriesCount, label: 'Серий в каталоге' },
    { value: props.productsCount, label: 'Позиций в каталоге' },
  ].filter((metric): metric is { value: number; label: string } => typeof metric.value === 'number' && metric.value > 0),
)
</script>

<template>
  <section v-if="metrics.length" class="border-y border-border bg-surface" aria-label="Показатели каталога">
    <dl class="container-app grid sm:grid-cols-3">
      <div
        v-for="(metric, index) in metrics"
        :key="metric.label"
        class="py-5 sm:px-6"
        :class="[
          index > 0 ? 'border-t border-border sm:border-l sm:border-t-0' : '',
          index === 0 ? 'sm:pl-0' : '',
          index === metrics.length - 1 ? 'sm:pr-0' : '',
        ]"
      >
        <dd class="font-mono text-2xl font-semibold text-ink">{{ formatter.format(metric.value) }}</dd>
        <dt class="mt-1 text-sm text-ink-muted">{{ metric.label }}</dt>
      </div>
    </dl>
  </section>
</template>
