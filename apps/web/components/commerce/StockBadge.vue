<script setup lang="ts">
// Бейдж наличия: один сегмент с фактическим статусом, а не переключатель из
// двух состояний. Раньше здесь рисовались оба сегмента («В наличии» и «Под
// заказ») одновременно — вкладка вкладкой, как у сегментированного
// переключателя, — и товар в списке выглядел так, будто он и в наличии, и под
// заказ. Наличие — это одно состояние, поэтому и сегмент один; при известном
// остатке рядом добавляется «N шт».
// Не интерактивен (это статус, а не переключатель), поэтому помечен role="img"
// с полной подписью, а содержимое скрыто от скринридера.
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
const statusLabel = computed(() => (inStock.value ? 'В наличии' : 'Под заказ'))
const label = computed(() => {
  if (!inStock.value) return 'Под заказ'
  return showQty.value ? `В наличии: ${props.quantity} шт` : 'В наличии'
})
</script>

<template>
  <span
    class="inline-flex max-w-full items-stretch overflow-hidden border border-border-strong bg-surface align-middle text-xs whitespace-nowrap"
    :class="props.size === 'md' ? 'text-sm' : undefined"
    role="img"
    :aria-label="label"
  >
    <span
      class="flex items-center gap-1.5 px-2 py-1 font-semibold leading-5"
      :class="inStock ? 'bg-success-soft text-success-text' : 'bg-warning-soft text-warning-text'"
      aria-hidden="true"
    >
      <span
        class="size-1.5 shrink-0 rounded-full"
        :class="inStock ? 'bg-success' : 'bg-warning-text'"
      />
      {{ statusLabel }}
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
