<script setup lang="ts">
// Детали заявки клиента. См. SITEMAP.md §6, §9 (snapshot цен/курса).
import type { OrderRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const { request } = useApi()

const STATUS_META: Record<string, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

// --- Status timeline ---
const STATUS_ORDER = ['NEW', 'IN_PROGRESS', 'SHIPPED', 'COMPLETED'] as const
const STATUS_LABELS: Record<string, string> = {
  NEW: 'Новая',
  IN_PROGRESS: 'В работе',
  SHIPPED: 'Отгружена',
  COMPLETED: 'Завершена',
  CANCELLED: 'Отменена',
}

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const order = ref<OrderRead | null>(null)
const acting = ref(false) // повтор/отмена в процессе

useHead({ title: computed(() => order.value ? `Заявка ${formatOrderNumber(order.value.seq, order.value.id)}` : 'Заявка') })

function rateSourceLabel(s: string | null | undefined): string {
  switch (s) {
    case 'BYN': return 'Без конвертации (BYN)'
    case 'FIXED': return 'По договору'
    case 'NBRB': return 'Текущий курс НБ РБ'
    default: return s || '—'
  }
}
// formatMoney/formatDateTime/formatOrderNumber — автоимпорт из utils/format.ts
function snapName(item: { product_snapshot?: Record<string, unknown> | null }): string {
  const name = item.product_snapshot?.name
  const sku = item.product_snapshot?.sku
  return (typeof name === 'string' && name) || (typeof sku === 'string' && sku) || '—'
}
function snapSku(item: { product_snapshot?: Record<string, unknown> | null }): string {
  const sku = item.product_snapshot?.sku
  return (typeof sku === 'string' && sku) || ''
}

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    order.value = await request<OrderRead>(`/api/v1/orders/${route.params.id}`)
  } catch (e) {
    if (getErrorStatus(e) === 404) notFound.value = true
    else error.value = getErrorMessage(e, 'Не удалось загрузить заявку')
  } finally {
    loading.value = false
  }
}

async function repeatOrder() {
  if (acting.value || !order.value) return
  acting.value = true
  error.value = ''
  try {
    await request(`/api/v1/orders/${order.value.id}/repeat`, { method: 'POST' })
    await navigateTo('/cart')
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось повторить заказ')
  } finally {
    acting.value = false
  }
}

async function cancelOrder() {
  if (acting.value || !order.value) return
  if (!confirm('Отменить заявку?')) return
  acting.value = true
  error.value = ''
  try {
    order.value = await request<OrderRead>(`/api/v1/orders/${order.value.id}/cancel`, {
      method: 'POST',
    })
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось отменить заявку')
  } finally {
    acting.value = false
  }
}

const canCancel = computed(
  () => order.value && (order.value.status === 'NEW' || order.value.status === 'IN_PROGRESS')
)

const statusSteps = computed(() => {
  if (!order.value) return []
  const currentStatus = order.value.status
  const isCancelled = currentStatus === 'CANCELLED'

  // Нормальный поток: NEW → IN_PROGRESS → SHIPPED → COMPLETED
  const currentIdx = STATUS_ORDER.indexOf(currentStatus as typeof STATUS_ORDER[number])
  const normalSteps = STATUS_ORDER.map((key, idx) => ({
    key,
    label: STATUS_LABELS[key],
    done: currentIdx >= 0 && idx < currentIdx,
    active: key === currentStatus,
  }))

  if (isCancelled) {
    // При отмене: показываем все шаги как неактивные (NEW — пройден) + CANCELLED как текущий
    return [
      ...normalSteps.map(s => ({ ...s, active: false, done: s.key === 'NEW' })),
      { key: 'CANCELLED', label: STATUS_LABELS.CANCELLED, done: false, active: true },
    ]
  }

  return normalSteps
})

// PDF-экспорт заявки (§16 п.25): job-паттерн, поллинг в composables/usePdfExport.ts.
const { activeId: pdfActiveId, error: pdfError, exportOrderPdf } = usePdfExport()
const pdfBusy = computed(() => pdfActiveId.value !== null)
// XLSX-экспорт заявки (для 1С): синхронный GET + blob в composables/useXlsxExport.ts.
const { activeId: xlsxActiveId, error: xlsxError, exportOrderXlsx } = useXlsxExport()
const xlsxBusy = computed(() => xlsxActiveId.value !== null)

function xlsxFileName(): string {
  const no = order.value?.seq ? `-${String(order.value.seq).padStart(3, '0')}` : ''
  return `order${no}-${route.params.id}.xlsx`
}

onMounted(load)
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/orders" class="hover:text-primary">Мои заявки</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Детали</span>
    </nav>

    <div v-if="loading" class="space-y-4">
      <div class="skeleton h-24 w-full"/>
      <div class="skeleton h-64 w-full"/>
    </div>

    <div v-else-if="notFound" class="card p-12 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Заявка не найдена</p>
      <NuxtLink to="/orders" class="btn-primary">К списку заявок</NuxtLink>
    </div>

    <div v-else-if="error && !order" class="card p-8 text-center">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div><button class="btn-primary" @click="load">Повторить</button></div>
    </div>

    <div v-else-if="order">
      <!-- Шапка -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <div class="flex items-center gap-3 mb-1">
            <h1 class="text-2xl font-bold">Заявка {{ formatOrderNumber(order.seq, order.id) }}</h1>
            <span :class="STATUS_META[order.status]?.cls || 'badge-info'">
              {{ STATUS_META[order.status]?.label || order.status }}
            </span>
          </div>
          <p class="text-sm text-ink-muted">
            от {{ formatDateTime(order.created_at) }}
            <span v-if="order.manager_id"> · менеджер назначен</span>
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button class="btn-secondary" :disabled="acting" @click="repeatOrder">
            <Icon name="heroicons:arrow-path" class="w-4 h-4" /> Повторить
          </button>
          <button class="btn-secondary" :disabled="pdfBusy" @click="exportOrderPdf(order.id)">
            <span v-if="pdfBusy" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
            <Icon v-else name="heroicons:document-arrow-down" class="w-4 h-4" />
            {{ pdfBusy ? 'Готовим PDF…' : 'Скачать PDF' }}
          </button>
          <button class="btn-secondary" :disabled="xlsxBusy" @click="exportOrderXlsx(order.id, xlsxFileName())">
            <span v-if="xlsxBusy" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
            <Icon v-else name="heroicons:table-cells" class="w-4 h-4" />
            {{ xlsxBusy ? 'Готовим Excel…' : 'Excel' }}
          </button>
          <button v-if="canCancel" class="btn-outline text-danger" :disabled="acting" @click="cancelOrder">
            <Icon name="heroicons:x-circle" class="w-4 h-4" /> Отменить
          </button>
        </div>
      </div>

      <!-- Status timeline -->
      <div class="flex items-center gap-2 mb-6 overflow-x-auto pb-2">
        <template v-for="(step, i) in statusSteps" :key="step.key">
          <div class="flex items-center gap-2 shrink-0">
            <div
              class="w-8 h-8 rounded-pill flex items-center justify-center text-xs font-bold"
              :class="step.active ? 'bg-primary text-white' : step.done ? 'bg-success text-white' : 'bg-canvas text-ink-faint'"
            >
              <Icon v-if="step.done" name="heroicons:check" class="w-4 h-4" />
              <span v-else>{{ i + 1 }}</span>
            </div>
            <span class="text-xs whitespace-nowrap" :class="step.active ? 'font-semibold text-ink' : 'text-ink-muted'">
              {{ step.label }}
            </span>
          </div>
          <div v-if="i < statusSteps.length - 1" class="w-8 h-px bg-border shrink-0" />
        </template>
      </div>

      <div v-if="error" class="badge-danger w-full justify-center py-2 mb-4">{{ error }}</div>
      <div v-if="pdfError || xlsxError" class="badge-warning w-full justify-center py-2 mb-4">{{ pdfError || xlsxError }}</div>

      <!-- Позиции -->
      <div class="card overflow-hidden mb-6">
        <div class="px-5 py-4 border-b border-border">
          <h3 class="font-semibold">Позиции ({{ order.items?.length || 0 }})</h3>
        </div>
        <!-- Таблица: планшет/десктоп -->
        <div class="overflow-x-auto hidden md:block">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-5 py-3 font-medium">Товар</th>
                <th class="px-5 py-3 font-medium text-center">Кол-во</th>
                <th class="px-5 py-3 font-medium text-right">Цена</th>
                <th class="px-5 py-3 font-medium text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in order.items" :key="item.id" class="border-t border-border">
                <td class="px-5 py-3">
                  <p class="font-medium">{{ snapName(item) }}</p>
                  <p class="text-xs text-ink-faint">
                    Артикул: {{ snapSku(item) }}
                    <NuxtLink v-if="snapSku(item)" :to="`/catalog/${snapSku(item)}`" class="text-primary hover:underline ml-1">→ каталог</NuxtLink>
                  </p>
                  <p v-if="item.note" class="text-xs text-ink-muted mt-1">📝 {{ item.note }}</p>
                </td>
                <td class="px-5 py-3 text-center">{{ item.quantity }}</td>
                <td class="px-5 py-3 text-right">{{ formatMoney(item.unit_price, item.currency_code) }}</td>
                <td class="px-5 py-3 text-right font-medium">{{ formatMoney(item.unit_price * item.quantity, item.currency_code) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Строки-блоки: мобильные (таблица на 390px не влезает) -->
        <div class="md:hidden px-5 py-1.5 divide-y divide-border">
          <article v-for="item in order.items" :key="item.id" class="py-3.5">
            <p class="font-medium leading-snug">{{ snapName(item) }}</p>
            <p class="text-xs text-ink-faint mt-0.5">
              Артикул: {{ snapSku(item) }}
              <NuxtLink v-if="snapSku(item)" :to="`/catalog/${snapSku(item)}`" class="text-primary hover:underline ml-1">→ каталог</NuxtLink>
            </p>
            <p v-if="item.note" class="text-xs text-ink-muted mt-1">📝 {{ item.note }}</p>
            <div class="flex items-center justify-between gap-3 mt-2">
              <span class="text-sm text-ink-muted">{{ item.quantity }} × {{ formatMoney(item.unit_price, item.currency_code) }}</span>
              <span class="font-bold whitespace-nowrap">{{ formatMoney(item.unit_price * item.quantity, item.currency_code) }}</span>
            </div>
          </article>
        </div>
      </div>

      <!-- Сводка + курс -->
      <div class="grid sm:grid-cols-2 gap-6">
        <div class="card p-5">
          <h3 class="font-semibold mb-3">Курс и валюта</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Валюта</span>
            <span class="font-medium">{{ order.currency_code }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Курс к BYN</span>
            <span class="font-medium">{{ order.exchange_rate }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Источник</span>
            <span class="font-medium">{{ rateSourceLabel(order.rate_source) }}</span>
          </div>
          <p class="text-xs text-ink-faint mt-3">Курс и цены зафиксированы на момент оформления и не пересчитываются.</p>
        </div>

        <div class="card p-5">
          <h3 class="font-semibold mb-3">Итого</h3>
          <div v-if="order.notes" class="text-sm py-1 mb-2">
            <span class="text-ink-muted">Комментарий: </span>
            <span>{{ order.notes }}</span>
          </div>
          <div class="flex justify-between text-xl font-bold pt-2 border-t border-border mt-2">
            <span>Сумма</span>
            <span>{{ formatMoney(order.total_amount, order.currency_code) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
