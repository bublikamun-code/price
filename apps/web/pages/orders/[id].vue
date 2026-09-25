<script setup lang="ts">
import type { OrderDetail } from '~/domain/api/v2/order.schema'
import { AppProblem } from '~/domain/api/v2/problem'
import { ORDER_STATUS_META } from '~/utils/order-status'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const { getById, cancel: cancelOrderV2, repeat } = useOrdersV2()

const STATUS_META = ORDER_STATUS_META

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const order = ref<OrderDetail | null>(null)
const acting = ref(false)
let loadSeq = 0
let isUnmounted = false
let isMounted = false

useHead({
  title: computed(() => order.value ? `Заявка ${formatOrderNumber(order.value.sequence, order.value.id)}` : 'Заявка'),
})

function problemMessage(cause: unknown, fallback: string): string {
  return cause instanceof AppProblem ? cause.message : getErrorMessage(cause, fallback)
}

function rateSourceLabel(source: string | null): string {
  switch (source) {
    case 'BYN': return 'Без конвертации (BYN)'
    case 'FIXED': return 'По договору'
    case 'NBRB': return 'Текущий курс НБ РБ'
    default: return source || '—'
  }
}

function deliveryLabel(method: OrderDetail['delivery']['method']): string {
  return method === 'PICKUP' ? 'Самовывоз' : 'Доставка'
}

async function load() {
  const seq = ++loadSeq
  const orderId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  if (!orderId) {
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  order.value = null
  try {
    const snapshot = await getById(orderId)
    if (seq !== loadSeq || isUnmounted) return
    order.value = snapshot.order
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    if (cause instanceof AppProblem && cause.status === 404) notFound.value = true
    else error.value = problemMessage(cause, 'Не удалось загрузить заявку')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }
}

async function repeatOrder() {
  if (acting.value || !order.value) return
  const current = order.value
  acting.value = true
  error.value = ''
  try {
    await repeat(current.id, current.version)
    await navigateTo('/cart')
  } catch (cause) {
    error.value = problemMessage(cause, 'Не удалось повторить заявку')
  } finally {
    acting.value = false
  }
}

const canCancel = computed(() => order.value?.status === 'NEW' || order.value?.status === 'IN_PROGRESS')

async function cancelOrder() {
  if (acting.value || !order.value || !canCancel.value) return
  if (!window.confirm('Отменить заявку? Это действие нельзя отменить.')) return
  const orderId = order.value.id
  acting.value = true
  error.value = ''
  try {
    const snapshot = await cancelOrderV2(orderId)
    order.value = snapshot.order
  } catch (cause) {
    error.value = problemMessage(cause, 'Не удалось отменить заявку')
  } finally {
    acting.value = false
  }
}

// Экспортные endpoints пока существуют только в v1. Операции заказа — v2.
const { activeId: pdfActiveId, error: pdfError, exportOrderPdf } = usePdfExport()
const pdfBusy = computed(() => pdfActiveId.value !== null)
const { activeId: xlsxActiveId, error: xlsxError, exportOrderXlsx } = useXlsxExport()
const xlsxBusy = computed(() => xlsxActiveId.value !== null)

function xlsxFileName(): string {
  const number = order.value?.sequence ? `-${String(order.value.sequence).padStart(3, '0')}` : ''
  return `order${number}-${route.params.id}.xlsx`
}

onMounted(() => {
  isMounted = true
  void load()
})

watch(
  () => (Array.isArray(route.params.id) ? route.params.id[0] : route.params.id),
  () => { if (isMounted) void load() },
)

onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
})
</script>

<template>
  <div class="min-w-0" data-testid="order-detail-page">
    <nav class="mb-5 flex min-h-11 items-center gap-2 text-sm text-ink-muted" aria-label="Навигация заявки">
      <NuxtLink to="/orders" class="inline-flex min-h-11 items-center hover:text-action">Мои заявки</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-3.5 text-ink-faint" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Детали</span>
    </nav>

    <div v-if="loading" class="space-y-5" data-testid="order-detail-loading" aria-live="polite" aria-busy="true">
      <UiSkeleton class="h-24 w-full" /><UiSkeleton class="h-56 w-full" /><UiSkeleton class="h-64 w-full" />
      <span class="sr-only">Загрузка заявки</span>
    </div>

    <UiEmptyState v-else-if="notFound" title="Заявка не найдена" description="Возможно, ссылка устарела или заявка недоступна в вашем контексте." icon="heroicons:archive-box-x-mark" data-testid="order-detail-not-found">
      <template #action><NuxtLink to="/orders" class="inline-flex min-h-11 items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">К списку заявок</NuxtLink></template>
    </UiEmptyState>

    <UiErrorState v-else-if="error && !order" title="Заявка недоступна" :description="error" data-testid="order-detail-error" @retry="load" />

    <article v-else-if="order" data-testid="order-detail">
      <PageHeading
        eyebrow="Мои заявки"
        :title="formatOrderNumber(order.sequence, order.id)"
        :description="`Создана ${formatDateTime(order.createdAt)} · версия ${order.version}${order.managerId ? ' · менеджер назначен' : ''}`"
      >
        <template #actions>
          <UiStatusBadge :tone="STATUS_META[order.status].tone" :label="STATUS_META[order.status].label" dot data-testid="order-detail-status" />
          <UiButton variant="outline" size="touch" :loading="acting" :disabled="acting" data-testid="order-detail-repeat" @click="repeatOrder"><template #leading><Icon name="heroicons:arrow-path" class="size-4" /></template>Повторить</UiButton>
          <UiButton variant="outline" size="touch" :loading="pdfBusy" :disabled="pdfBusy" :data-testid="`order-detail-pdf-${order.id}`" @click="exportOrderPdf(order.id)"><template #leading><Icon name="heroicons:document-arrow-down" class="size-4" /></template>{{ pdfBusy ? 'Готовим PDF…' : 'PDF' }}</UiButton>
          <UiButton variant="outline" size="touch" :loading="xlsxBusy" :disabled="xlsxBusy" :data-testid="`order-detail-xlsx-${order.id}`" @click="exportOrderXlsx(order.id, xlsxFileName())"><template #leading><Icon name="heroicons:table-cells" class="size-4" /></template>{{ xlsxBusy ? 'Готовим Excel…' : 'Excel' }}</UiButton>
          <UiButton v-if="canCancel" variant="danger" size="touch" :loading="acting" :disabled="acting" data-testid="order-detail-cancel" @click="cancelOrder"><template #leading><Icon name="heroicons:x-circle" class="size-4" /></template>Отменить</UiButton>
        </template>
      </PageHeading>

      <UiErrorState v-if="error" class="mt-4" title="Действие не выполнено" :description="error" data-testid="order-detail-action-error" />
      <UiErrorState v-if="pdfError || xlsxError" class="mt-4" title="Экспорт недоступен" :description="pdfError || xlsxError || ''" data-testid="order-detail-export-error" />

      <section class="mt-6 border-b border-border pb-6" aria-labelledby="order-status-title">
        <div class="mb-4 flex items-center justify-between gap-4">
          <h2 id="order-status-title" class="text-lg font-bold text-ink">Статус</h2>
          <span class="text-xs text-ink-muted">Обновлён {{ formatDateTime(order.updatedAt) }}</span>
        </div>
        <OrderStatusTimeline :status="order.status" />
      </section>

      <section class="mt-7" aria-labelledby="order-lines-title">
        <div class="flex items-end justify-between gap-4 border-b border-border pb-3">
          <div><p class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Состав</p><h2 id="order-lines-title" class="mt-1 text-lg font-bold text-ink">Позиции заявки</h2></div>
          <span class="numeric text-sm text-ink-muted">{{ order.lines.length }} {{ pluralize(order.lines.length, 'позиция', 'позиции', 'позиций') }}</span>
        </div>
        <div class="border-b border-border" data-testid="order-detail-lines">
          <OrderLineRecord v-for="item in order.lines" :key="item.id" :line="item" readonly />
        </div>
      </section>

      <div class="mt-7 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div class="min-w-0 border-y border-border">
          <section class="border-b border-border px-4 py-4 sm:px-5" aria-labelledby="order-delivery-title">
            <h2 id="order-delivery-title" class="text-sm font-semibold text-ink">Получение</h2>
            <dl class="mt-3 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div class="flex justify-between gap-4 sm:block"><dt class="text-ink-muted">Способ</dt><dd class="font-medium text-ink sm:mt-1">{{ deliveryLabel(order.delivery.method) }}</dd></div>
              <div v-if="order.delivery.pickupPoint" class="flex justify-between gap-4 sm:block"><dt class="text-ink-muted">Точка</dt><dd class="text-right font-medium text-ink sm:mt-1 sm:text-left">{{ order.delivery.pickupPoint }}</dd></div>
              <div v-if="order.delivery.address" class="flex justify-between gap-4 sm:col-span-2 sm:block"><dt class="text-ink-muted">Адрес</dt><dd class="text-right font-medium text-ink sm:mt-1 sm:text-left">{{ order.delivery.address }}</dd></div>
              <div v-if="order.delivery.preferredDate" class="flex justify-between gap-4 sm:block"><dt class="text-ink-muted">Желаемая дата</dt><dd class="font-medium text-ink sm:mt-1">{{ formatDate(order.delivery.preferredDate) }}</dd></div>
            </dl>
            <p v-if="order.delivery.comment" class="mt-4 border-t border-border pt-3 text-sm leading-6 text-ink-muted">{{ order.delivery.comment }}</p>
          </section>

          <section class="px-4 py-4 sm:px-5" aria-labelledby="order-rate-title">
            <h2 id="order-rate-title" class="text-sm font-semibold text-ink">Курс и фиксация цены</h2>
            <dl class="mt-3 space-y-2 text-sm">
              <div class="flex justify-between gap-4"><dt class="text-ink-muted">Валюта</dt><dd class="font-medium text-ink">{{ order.total.currency }}</dd></div>
              <div class="flex justify-between gap-4"><dt class="text-ink-muted">Курс к BYN</dt><dd class="numeric font-medium text-ink">{{ order.exchangeRate.value }}</dd></div>
              <div class="flex justify-between gap-4"><dt class="text-ink-muted">Источник</dt><dd class="text-right font-medium text-ink">{{ rateSourceLabel(order.exchangeRate.source) }}</dd></div>
            </dl>
            <p class="mt-3 text-xs leading-5 text-ink-muted">Курс и цены зафиксированы на момент оформления и не пересчитываются.</p>
          </section>
        </div>

        <aside class="bg-service p-5 text-service-ink lg:sticky lg:top-24" aria-labelledby="order-total-title">
          <p class="text-xs font-semibold uppercase tracking-wider text-service-muted">Итог</p>
          <h2 id="order-total-title" class="mt-1 text-lg font-bold">Сумма заявки</h2>
          <p v-if="order.notes" class="mt-4 border-b border-service-border pb-4 text-sm leading-6 text-service-muted">{{ order.notes }}</p>
          <div class="mt-5 flex items-baseline justify-between gap-4 border-t border-service-border pt-4">
            <span class="font-semibold">Всего</span>
            <strong class="numeric text-xl font-bold">{{ formatMoney(order.total.amount, order.total.currency) }}</strong>
          </div>
          <p class="mt-4 text-xs leading-5 text-service-muted">Повторная заявка использует текущую версию {{ order.version }} исходной заявки.</p>
        </aside>
      </div>
    </article>
  </div>
</template>
