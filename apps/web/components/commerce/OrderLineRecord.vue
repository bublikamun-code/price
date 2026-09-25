<script setup lang="ts">
import type { CartLine } from '~/domain/api/v2/cart.schema'
import type { OrderLine } from '~/domain/api/v2/order.schema'

const props = withDefaults(
  defineProps<{
    line: CartLine | OrderLine
    busy?: boolean
    readonly?: boolean
  }>(),
  { busy: false, readonly: false },
)

const emit = defineEmits<{
  change: [delta: number]
  remove: []
}>()

const isCartLine = computed(() => 'stockStatus' in props.line)
const canEdit = computed(() => !props.readonly && isCartLine.value)
const lineKey = computed(() =>
  isCartLine.value ? (props.line as CartLine).productId : (props.line as OrderLine).id,
)
const stockLabel = computed(() => {
  if (!isCartLine.value) return null
  const line = props.line as CartLine
  return line.stockStatus === 'IN_STOCK' ? 'В наличии' : 'Под заказ'
})
const stockTone = computed<'success' | 'warning'>(() =>
  isCartLine.value && (props.line as CartLine).stockStatus === 'IN_STOCK'
    ? 'success'
    : 'warning',
)
</script>

<template>
  <article
    class="grid gap-3 border-b border-border py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-6"
    :data-testid="`order-line-${lineKey}`"
  >
    <div class="flex min-w-0 gap-3">
      <div
        class="flex size-14 shrink-0 items-center justify-center border border-border bg-surface-2 text-ink-muted"
        aria-hidden="true"
      >
        <Icon name="heroicons:package" class="size-6" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="numeric text-xs font-semibold text-ink">{{ line.sku || 'Артикул недоступен' }}</span>
          <UiStatusBadge
            v-if="stockLabel"
            :tone="stockTone"
            :label="stockLabel"
            dot
          />
          <span v-if="props.readonly" class="text-xs text-ink-muted">Зафиксировано</span>
        </div>
        <NuxtLink
          v-if="line.sku"
          :to="`/catalog/${line.sku}`"
          class="mt-1 block text-sm font-semibold leading-5 text-ink hover:text-action"
        >
          {{ line.name || 'Позиция заявки' }}
        </NuxtLink>
        <p v-else class="mt-1 text-sm font-semibold leading-5 text-ink">
          {{ line.name || 'Позиция заявки' }}
        </p>
        <p v-if="line.note" class="mt-1 text-xs leading-5 text-ink-muted">
          {{ line.note }}
        </p>
      </div>
    </div>

    <div class="flex items-end justify-between gap-4 pl-[4.25rem] sm:w-64 sm:justify-end sm:pl-0">
      <div v-if="canEdit" class="flex h-11 items-center border border-border bg-surface" role="group" :aria-label="`Количество: ${line.name}`">
        <button
          type="button"
          class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40"
          :disabled="(line as CartLine).quantity <= 1 || busy"
          :aria-label="`Уменьшить количество: ${line.name}`"
          @click="emit('change', -1)"
        >
          <Icon name="heroicons:minus" class="size-4" aria-hidden="true" />
        </button>
        <span class="numeric w-8 text-center text-sm font-semibold" aria-live="polite">
          {{ line.quantity }}
        </span>
        <button
          type="button"
          class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40"
          :disabled="busy"
          :aria-label="`Увеличить количество: ${line.name}`"
          @click="emit('change', 1)"
        >
          <Icon name="heroicons:plus" class="size-4" aria-hidden="true" />
        </button>
      </div>
      <div v-else class="text-left sm:text-right">
        <span class="numeric block text-xs text-ink-muted">
          {{ line.quantity }} × {{ formatMoney(line.unitPrice.amount, line.unitPrice.currency) }}
        </span>
        <strong class="numeric mt-0.5 block text-sm font-bold text-ink">
          {{ formatMoney(line.lineTotal.amount, line.lineTotal.currency) }}
        </strong>
      </div>

      <strong v-if="canEdit" class="numeric whitespace-nowrap text-sm font-bold text-ink">
        {{ formatMoney(line.lineTotal.amount, line.lineTotal.currency) }}
      </strong>
    </div>

    <button
      v-if="canEdit"
      type="button"
      class="ml-[4.25rem] inline-flex min-h-11 items-center gap-2 self-start text-sm font-semibold text-danger-text hover:underline disabled:opacity-50 sm:col-start-2 sm:ml-0"
      :disabled="busy"
      @click="emit('remove')"
    >
      <Icon name="heroicons:trash" class="size-4" aria-hidden="true" />
      Удалить
    </button>
  </article>
</template>
