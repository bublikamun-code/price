<script setup lang="ts">
const emit = defineEmits<{ open: [] }>()
const cart = useCartV2()
const summary = computed(() => cart.store.cart)
const count = computed(() => summary.value?.totalItems ?? 0)
const total = computed(() => summary.value?.total)

function openReview() {
  emit('open')
}
</script>

<template>
  <button
    type="button"
    class="flex w-full items-center gap-3 border border-service bg-service px-4 py-3 text-left text-ink-on-service transition-colors hover:bg-service/90"
    :aria-label="`Текущая заявка: ${count} позиций. Открыть просмотр`"
    @click="openReview"
  >
    <span class="min-w-0 flex-1">
      <span class="block text-xs font-semibold uppercase tracking-wide text-ink-on-service/70">Текущая заявка</span>
      <strong class="mt-0.5 block text-sm font-semibold">
        {{ count }} {{ count === 1 ? 'позиция' : count < 5 ? 'позиции' : 'позиций' }}
        <span v-if="total" class="font-normal text-ink-on-service/70"> · {{ formatMoney(total.amount, total.currency) }}</span>
      </strong>
    </span>
    <Icon name="heroicons:arrow-right" class="size-5 shrink-0" aria-hidden="true" />
  </button>
</template>
