<script setup lang="ts">
// Детали заявки для менеджера. См. SITEMAP.md §7, §9 (FSM), §11 (audit).
import type { OrderRead, OrderStatus } from '~/types/api'
import { ORDER_STATUS_META } from '~/utils/order-status'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })

const route = useRoute()
const { request } = useApi()

const STATUS_META = ORDER_STATUS_META

const STATUS_OPTIONS: OrderStatus[] = ['NEW', 'IN_PROGRESS', 'SHIPPED', 'COMPLETED', 'CANCELLED']

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const order = ref<OrderRead | null>(null)
const selectedStatus = ref<OrderStatus>('NEW')
const saving = ref(false)

useHead({ title: computed(() => `Заявка №${order.value ? order.value.id.slice(0, 8) : ''} — Менеджер`) })

function formatDate(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}
function snapName(item: { product_snapshot?: Record<string, unknown> | null }): string {
  const name = item.product_snapshot?.name
  const sku = item.product_snapshot?.sku
  return (typeof name === 'string' && name) || (typeof sku === 'string' && sku) || '—'
}
function shortId(id: string): string {
  return id.slice(0, 8)
}

// XLSX-экспорт заявки (для 1С): синхронный GET + blob в composables/useXlsxExport.ts.
const { activeId: xlsxActiveId, error: xlsxError, exportOrderXlsx } = useXlsxExport()
const xlsxBusy = computed(() => xlsxActiveId.value !== null)

function xlsxFileName(): string {
  const no = order.value?.seq ? `-${String(order.value.seq).padStart(3, '0')}` : ''
  return `order${no}-${shortId(String(route.params.id))}.xlsx`
}

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    order.value = await request<OrderRead>(`/api/v1/manager/orders/${route.params.id}`)
    selectedStatus.value = order.value.status
  } catch (e) {
    if (getErrorStatus(e) === 404) notFound.value = true
    else error.value = getErrorMessage(e, 'Не удалось загрузить заявку')
  } finally {
    loading.value = false
  }
}

async function saveStatus() {
  if (!order.value || saving.value) return
  if (selectedStatus.value === order.value.status) return
  saving.value = true
  error.value = ''
  try {
    order.value = await request<OrderRead>(`/api/v1/manager/orders/${order.value.id}`, {
      method: 'PATCH',
      body: { status: selectedStatus.value },
    })
  } catch (e) {
    // 409 — запрещённый переход; восстанавливаем select.
    selectedStatus.value = order.value!.status
    error.value = getErrorMessage(e, 'Не удалось изменить статус (возможно, переход запрещён)')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/manager/orders" class="hover:text-primary">Заявки</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Детали</span>
    </nav>

    <div v-if="loading" class="space-y-4">
      <div class="skeleton h-24 w-full"/>
      <div class="skeleton h-64 w-full"/>
    </div>

    <div v-else-if="notFound" class="border border-border bg-surface p-6 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="size-8 mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Заявка не найдена</p>
      <NuxtLink to="/manager/orders" class="btn-primary">К списку заявок</NuxtLink>
    </div>

    <div v-else-if="error && !order" class="border border-danger/50 bg-danger-soft p-5">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div><button class="btn-outline min-h-11" @click="load">Повторить</button></div>
    </div>

    <div v-else-if="order">
      <!-- Шапка -->
      <PageHeading
        eyebrow="Заявки"
        :title="`Заявка №${shortId(order.id)}`"
        :description="`от ${formatDate(order.created_at)} · клиент №${shortId(order.client_id)}`"
      >
        <template #actions>
          <UiStatusBadge :tone="STATUS_META[order.status].tone" :label="STATUS_META[order.status].label" dot />
          <UiButton variant="outline" size="touch" :loading="xlsxBusy" :disabled="xlsxBusy" @click="exportOrderXlsx(order.id, xlsxFileName())">
            <template #leading><Icon name="heroicons:table-cells" class="size-4" /></template>
            {{ xlsxBusy ? 'Готовим Excel…' : 'Excel' }}
          </UiButton>
        </template>
      </PageHeading>

      <div v-if="error || xlsxError" class="badge-danger w-full justify-center py-2 mb-4">{{ error || xlsxError }}</div>

      <!-- Управление статусом -->
      <div class="mb-5 border border-border bg-surface p-4">
        <h3 class="font-semibold mb-3">Управление</h3>
        <div class="flex flex-wrap items-center gap-3">
          <label class="text-sm text-ink-muted" for="status">Статус:</label>
          <select id="status" v-model="selectedStatus" class="input min-h-11 w-auto">
            <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">{{ STATUS_META[s].label }}</option>
          </select>
          <button
            class="btn-primary min-h-11"
            :disabled="saving || selectedStatus === order.status"
            @click="saveStatus"
          >
            <span v-if="saving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"/>
            <Icon v-else name="heroicons:check" class="w-4 h-4" />
            Применить
          </button>
          <p class="text-xs text-ink-faint w-full mt-1">
            Допустимые переходы: NEW → В работе/Отменена, В работе → Отгружена/Отменена, Отгружена → Завершена/Отменена.
          </p>
        </div>
      </div>

      <!-- Счёт на оплату (§16 п.40) -->
      <OrderInvoicePanel :order-id="order.id" :order-status="order.status" />

      <!-- Позиции -->
      <div class="mb-5 border border-border bg-surface">
        <div class="px-5 py-4 border-b border-border">
          <h3 class="font-semibold">Позиции ({{ order.items?.length || 0 }})</h3>
        </div>
        <div class="overflow-x-auto">
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
                  <p class="text-xs text-ink-faint">Артикул: {{ item.product_snapshot?.sku || '—' }}</p>
                  <p v-if="item.note" class="text-xs text-ink-muted mt-1">{{ item.note }}</p>
                </td>
                <td class="px-5 py-3 text-center">{{ item.quantity }}</td>
                <td class="px-5 py-3 text-right">{{ formatMoney(item.unit_price, item.currency_code) }}</td>
                <td class="px-5 py-3 text-right font-medium">{{ formatMoney(item.unit_price * item.quantity, item.currency_code) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Сводка -->
      <div class="grid sm:grid-cols-2 gap-6">
        <div class="border border-border bg-surface p-4">
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
            <span class="font-medium">{{ order.rate_source || '—' }}</span>
          </div>
        </div>
        <div class="border border-border bg-surface p-4">
          <h3 class="font-semibold mb-3">Итого</h3>
          <div v-if="order.notes" class="text-sm py-1 mb-2">
            <span class="text-ink-muted">Комментарий: </span>
            <span>{{ order.notes }}</span>
          </div>
          <div class="flex justify-between text-xl font-bold pt-2 border-t border-border mt-2">
            <span>Сумма</span>
            <span>{{ order.total_amount }} {{ order.currency_code }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
