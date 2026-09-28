<script setup lang="ts">
import type { CatalogProduct } from '~/domain/api/v2/catalog.schema'

const props = withDefaults(
  defineProps<{
    product: CatalogProduct
    quantity: number
    inCartQuantity?: number
    loading?: boolean
    added?: boolean
    favorite?: boolean
    /** Списки v1 отдают только название бренда и статус без остатка. */
    brandName?: string
    stockLabel?: string
    available?: boolean
    /** Зачёркнутая розничная цена для списков, где она отдаётся отдельно. */
    comparePrice?: string
    /** Префикс data-testid для страниц, рендерящих запись вне каталога. */
    testIdPrefix?: string
  }>(),
  {
    inCartQuantity: 0,
    loading: false,
    added: false,
    favorite: false,
    brandName: '',
    stockLabel: '',
    available: undefined,
    comparePrice: '',
    testIdPrefix: '',
  },
)
const emit = defineEmits<{
  'add': []
  'favorite': []
  'quantity-change': [value: number]
}>()

const defaultStockLabel = computed(() => {
  if (props.product.stockStatus === 'PREORDER') return 'Под заказ'
  if (props.product.stockQuantity != null) return `${props.product.stockQuantity} шт`
  return 'В наличии'
})
const stockText = computed(() => props.stockLabel || defaultStockLabel.value)
const brandText = computed(() => props.brandName || props.product.brand?.name || 'Без бренда')
const isAvailable = computed(() =>
  props.available
  ?? (props.product.stockStatus !== 'PREORDER' && props.product.stockQuantity !== 0),
)
const actionLabel = computed(() => {
  if (!isAvailable.value) return 'Недоступно'
  if (props.added) return 'Добавлено'
  if (props.inCartQuantity) return 'Обновить'
  return 'Добавить'
})
</script>

<template>
  <article class="flex gap-3 border-b border-border py-4 last:border-b-0" :data-testid="`product-record-${product.id}`">
    <ProductPhoto
      :media="product.thumbnail"
      :alt="product.name"
      class="size-20 shrink-0 border border-border"
      :data-testid="testIdPrefix ? `${testIdPrefix}-media` : undefined"
    />
    <div class="min-w-0 flex-1">
      <div class="flex items-center justify-between gap-2">
        <span class="flex min-w-0 items-center gap-2 text-xs">
          <span class="truncate font-semibold text-ink">{{ brandText }}</span>
          <span class="shrink-0 font-medium" :class="isAvailable ? 'text-success' : 'text-warning-text'">{{ stockText }}</span>
        </span>
        <button
          type="button"
          class="inline-flex size-11 shrink-0 items-center justify-center text-ink-muted hover:text-action"
          :aria-label="favorite ? `Убрать ${product.name} из избранного` : `Добавить ${product.name} в избранное`"
          :aria-pressed="favorite"
          :data-testid="testIdPrefix ? `${testIdPrefix}-favorite-${product.id}` : undefined"
          @click="emit('favorite')"
        >
          <Icon :name="favorite ? 'heroicons:heart-solid' : 'heroicons:heart'" class="size-5" aria-hidden="true" />
        </button>
      </div>
      <NuxtLink :to="`/catalog/${encodeURIComponent(product.sku)}`" class="mt-1 block line-clamp-2 text-sm font-semibold leading-5 text-ink hover:text-action">{{ product.name }}</NuxtLink>
      <p class="numeric mt-1 truncate text-xs text-ink-muted">{{ product.sku }}<span v-if="product.series"> · {{ product.series.name }}</span></p>
      <div class="mt-3 flex items-end justify-between gap-3">
        <div class="min-w-0">
          <strong v-if="Number(product.clientPrice.amount) > 0" class="numeric block text-base font-bold text-ink">{{ formatMoney(product.clientPrice.amount, product.clientPrice.currency) }}</strong>
          <span v-else class="text-sm text-ink-muted">Цена по запросу</span>
          <span v-if="Number(product.clientPrice.amount) > 0" class="block text-xs text-ink-muted">за шт.</span>
          <span v-if="comparePrice" class="numeric block text-xs text-ink-muted line-through">{{ comparePrice }}</span>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <div class="flex h-11 items-center border border-border bg-surface" role="group" :aria-label="`Количество товара «${product.name}»`">
            <button
              type="button"
              class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40"
              :disabled="quantity <= 1 || !isAvailable"
              :aria-label="`Уменьшить количество товара «${product.name}»`"
              :data-testid="testIdPrefix ? `${testIdPrefix}-qty-decrease-${product.id}` : undefined"
              @click="emit('quantity-change', quantity - 1)"
            >
              <Icon name="heroicons:minus" class="size-4" aria-hidden="true" />
            </button>
            <span class="numeric w-7 text-center text-sm font-semibold" :data-testid="testIdPrefix ? `${testIdPrefix}-quantity-${product.id}` : undefined">{{ quantity }}</span>
            <button
              type="button"
              class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40"
              :disabled="!isAvailable || (product.stockQuantity != null && quantity >= product.stockQuantity)"
              :aria-label="`Увеличить количество товара «${product.name}»`"
              :data-testid="testIdPrefix ? `${testIdPrefix}-qty-increase-${product.id}` : undefined"
              @click="emit('quantity-change', quantity + 1)"
            >
              <Icon name="heroicons:plus" class="size-4" aria-hidden="true" />
            </button>
          </div>
          <UiButton
            size="touch"
            :loading="loading"
            :disabled="!isAvailable"
            :aria-label="`${actionLabel} товар «${product.name}»`"
            :data-testid="testIdPrefix ? `${testIdPrefix}-add-${product.id}` : undefined"
            class="px-3"
            @click="emit('add')"
          >
            <Icon v-if="!loading" :name="added || inCartQuantity ? 'heroicons:check' : 'heroicons:plus'" class="size-4" aria-hidden="true" />
            <span class="sr-only sm:not-sr-only">{{ actionLabel }}</span>
          </UiButton>
        </div>
      </div>
    </div>
  </article>
</template>
