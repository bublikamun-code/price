<script setup lang="ts">
// Бейдж скидки за объём: «от 10 шт −2%» (§16 п.41).
//
// Показывается в двух смыслах, и различать их важно:
//   * каталог — «от 10 шт −2%», то есть подсказка лестницы: цена за штуку ещё
//     не изменилась, но клиенту выгодно взять больше;
//   * корзина/заказ — та же ступень, но уже применённая к unitPrice строки.
//
// Поэтому проп `applied`: в каталоге это обещание, в корзине — факт.
// Не интерактивен (статус, а не действие), поэтому role="img" с полной
// подписью, а содержимое скрыто от скринридера — как у StockBadge.
import { formatPercent } from '~/utils/format'

const props = withDefaults(
  defineProps<{
    minQty: number
    discountPercent: number
    /** Ступень уже учтена в цене строки, а не только предложена. */
    applied?: boolean
    size?: 'sm' | 'md'
  }>(),
  { applied: false, size: 'sm' },
)

const amount = computed(() => formatPercent(props.discountPercent))
const shortLabel = computed(() => `от ${props.minQty} шт −${amount.value}`)
const label = computed(() =>
  props.applied
    ? `Скидка за объём применена: от ${props.minQty} шт минус ${amount.value}`
    : `Скидка за объём: от ${props.minQty} шт минус ${amount.value}`,
)
</script>

<template>
  <span
    class="inline-flex max-w-full items-center border border-success/40 bg-success-soft px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-success-text"
    :class="props.size === 'md' ? 'py-1 text-sm' : undefined"
    role="img"
    :aria-label="label"
  >
    <span aria-hidden="true">{{ shortLabel }}</span>
  </span>
</template>
