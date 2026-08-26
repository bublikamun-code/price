<script setup lang="ts">
// Детали заявки для менеджера. См. SITEMAP.md §7, §9 (FSM), §11 (audit).
import type { OrderRead, OrderStatus } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })

const route = useRoute()
const { request } = useApi()

const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

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

    <div v-else-if="notFound" class="card p-12 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Заявка не найдена</p>
      <NuxtLink to="/manager/orders" class="btn-primary">К списку заявок</NuxtLink>
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
            <h1 class="text-2xl font-bold">Заявка №{{ shortId(order.id) }}</h1>
            <span :class="STATUS_META[order.status].cls">{{ STATUS_META[order.status].label }}</span>
          </div>
          <p class="text-sm text-ink-muted">
            от {{ formatDate(order.created_at) }} · клиент №{{ shortId(order.client_id) }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button class="btn-secondary" :disabled="xlsxBusy" @click="exportOrderXlsx(order.id, xlsxFileName())">
            <span v-if="xlsxBusy" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
            <Icon v-else name="heroicons:table-cells" class="w-4 h-4" />
            {{ xlsxBusy ? 'Готовим Excel…' : 'Excel' }}
          </button>
        </div>
      </div>

      <div v-if="error || xlsxError" class="badge-danger w-full justify-center py-2 mb-4">{{ error || xlsxError }}</div>

      <!-- Управление статусом -->
      <div class="card p-5 mb-6">
        <h3 class="font-semibold mb-3">Управление</h3>
        <div class="flex flex-wrap items-center gap-3">
          <label class="text-sm text-ink-muted" for="status">Статус:</label>
          <select id="status" v-model="selectedStatus" class="input py-2 w-auto">
            <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">{{ STATUS_META[s].label }}</option>
          </select>
          <button
            class="btn-primary"
            :disabled="saving || selectedStatus === order.status"
            @click="saveStatus"
          >
            <span v-if="saving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            <Icon v-else name="heroicons:check" class="w-4 h-4" />
            Применить
          </button>
          <p class="text-xs text-ink-faint w-full mt-1">
            Допустимые переходы: NEW → В работе/Отменена, В работе → Отгружена/Отменена, Отгружена → Завершена/Отменена.
          </p>
        </div>
      </div>

      <!-- Позиции -->
      <div class="card overflow-hidden mb-6">
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
                  <p v-if="item.note" class="text-xs text-ink-muted mt-1">📝 {{ item.note }}</p>
                </td>
                <td class="px-5 py-3 text-center">{{ item.quantity }}</td>
                <td class="px-5 py-3 text-right">{{ item.unit_price }} {{ item.currency_code }}</td>
                <td class="px-5 py-3 text-right font-medium">{{ (item.unit_price * item.quantity).toFixed(2) }} {{ item.currency_code }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Сводка -->
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
            <span class="font-medium">{{ order.rate_source || '—' }}</span>
          </div>
        </div>
        <div class="card p-5">
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
