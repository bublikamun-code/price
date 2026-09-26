<script setup lang="ts">
// Бейдж наличия в форме соседних кнопок — та же жёсткая сегментированная
// эстетика, что у степпера количества рядом (общая рамка, разделители, без
// скруглений). Активный сегмент залит tone-soft, неактивные приглушены;
// при известном остатке добавляется соседний сегмент «N шт». Не интерактивен
// (это статус, а не переключатель), поэтому помечен role="img" с полной
// подписью, а сегменты скрыты от скринридера — иначе он прочитал бы оба
// состояния подряд.
const props = withDefaults(
  defineProps<{
    status: 'IN_STOCK' | 'PREORDER'
    quantity?: number | null
    size?: 'sm' | 'md'
  }>(),
  { quantity: null, size: 'sm' },
)

const inStock = computed(() => props.status === 'IN_STOCK')
const showQty = computed(() => inStock.value && props.quantity != null && props.quantity > 0)
const label = computed(() => {
  if (!inStock.value) return 'Под заказ'
  return showQty.value ? `В наличии: ${props.quantity} шт` : 'В наличии'
})
</script>

<template>
  <span
    class="inline-flex max-w-full items-stretch overflow-hidden border border-border-strong bg-surface align-middle text-xs"
    :class="props.size === 'md' ? 'text-sm' : undefined"
    role="img"
    :aria-label="label"
  >
    <span
      class="flex items-center gap-1.5 px-2 py-1 font-semibold leading-5"
      :class="inStock ? 'bg-success-soft text-success-text' : 'text-ink-faint'"
      aria-hidden="true"
    >
      <span
        class="size-1.5 shrink-0 rounded-full"
        :class="inStock ? 'bg-success' : 'bg-ink-faint'"
      />
      В наличии
    </span>
    <span
      class="flex items-center border-l border-border px-2 py-1 font-semibold leading-5"
      :class="!inStock ? 'bg-warning-soft text-warning-text' : 'text-ink-faint'"
      aria-hidden="true"
    >
      Под заказ
    </span>
    <span
      v-if="showQty"
      class="numeric flex items-center border-l border-border px-2 py-1 font-semibold leading-5 text-ink"
      aria-hidden="true"
    >
      {{ props.quantity }} шт
    </span>
  </span>
</template>
