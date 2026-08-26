<script setup lang="ts">
// Управление каталогом (менеджер, Этап 8 п.20-2): список товаров с фильтрами,
// точечный PATCH ручной цены (override_price) и статуса остатка.
// См. ARCHITECTURE_PLAN.md §6, SITEMAP.md /manager/catalog.
import type { ManagerBrand, ManagerProductPage, ManagerProductRow, StockStatus } from '~/types/api'

// stock_qty приходит с бэка позже — расширяем локально (types/api.ts пока без поля).
type ProductRow = ManagerProductRow & { stock_qty?: number | null }
type ProductPage = Omit<ManagerProductPage, 'data'> & { data: ProductRow[] }

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Управление каталогом — Менеджер' })

const { request } = useApi()
/* закрытие модалки по клику на подложку — только если нажатие началось на ней (иначе срабатывает при выделении текста с уводом мыши) */
const overlayDown = ref(false)

const STOCK_META: Record<StockStatus, { label: string; cls: string }> = {
  IN_STOCK: { label: 'В наличии', cls: 'badge-success' },
  PREORDER: { label: 'Под заказ', cls: 'badge-warning' },
  ARCHIVED: { label: 'Архив', cls: 'badge-danger' },
}

const loading = ref(true)
const error = ref('')
const rows = ref<ProductRow[]>([])
const total = ref(0)
const page = ref(1)
const perPage = ref(20)

// Фильтры: q — поле ввода (сабмит по Enter/кнопке), appliedQ — применённое.
const q = ref('')
const appliedQ = ref('')
const brandId = ref('')
const stock = ref<'' | StockStatus>('')

const brands = ref<ManagerBrand[]>([])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))
const shownFrom = computed(() => (total.value === 0 ? 0 : (page.value - 1) * perPage.value + 1))
const shownTo = computed(() => Math.min(page.value * perPage.value, total.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<ProductPage>('/api/v1/manager/products', {
      query: {
        q: appliedQ.value || undefined,
        brand_id: brandId.value || undefined,
        stock: stock.value || undefined,
        page: page.value,
        per_page: perPage.value,
      },
    })
    rows.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить товары')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  load()
}

function applySearch() {
  appliedQ.value = q.value.trim()
  applyFilters()
}

function resetFilters() {
  q.value = ''
  appliedQ.value = ''
  brandId.value = ''
  stock.value = ''
  perPage.value = 20
  applyFilters()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// Бренды для фильтра — тот же источник, что и на странице брендов.
async function loadBrands() {
  try {
    brands.value = await request<ManagerBrand[]>('/api/v1/manager/brands')
  } catch {
    // Фильтр по бренду необязателен — молча оставляем пустым.
  }
}

// --- Редактирование товара (override_price + stock_status) ---
const editing = ref<ProductRow | null>(null)
const editPrice = ref('')
const editResetPrice = ref(false)
const editStock = ref<StockStatus>('IN_STOCK')
const editStockQty = ref('')
const saving = ref(false)
const editError = ref('')
const editSuccess = ref(false)
let successTimer: ReturnType<typeof setTimeout> | null = null

function openEdit(p: ProductRow) {
  editing.value = p
  editPrice.value = p.override_price !== null ? String(p.override_price) : ''
  editResetPrice.value = false
  editStock.value = p.stock_status
  editStockQty.value = p.stock_qty !== null && p.stock_qty !== undefined ? String(p.stock_qty) : ''
  editError.value = ''
  editSuccess.value = false
  if (successTimer) clearTimeout(successTimer)
}

function closeEdit() {
  editing.value = null
  if (successTimer) {
    clearTimeout(successTimer)
    successTimer = null
  }
}

async function submitEdit() {
  if (!editing.value || saving.value) return
  editError.value = ''
  editSuccess.value = false

  const body: { stock_status: StockStatus; override_price?: number | null; stock_qty?: number } = { stock_status: editStock.value }
  if (editResetPrice.value) {
    body.override_price = null // явный сброс ручной цены
  } else {
    const t = editPrice.value.trim()
    if (t !== '') {
      const n = Number(t.replace(',', '.'))
      if (!Number.isFinite(n) || n < 0) {
        editError.value = 'Цена менеджера должна быть числом ≥ 0'
        return
      }
      body.override_price = n
    }
  }

  // Остаток: пусто = не менять.
  const qtyRaw = editStockQty.value.trim()
  if (qtyRaw !== '') {
    const qty = Number(qtyRaw.replace(',', '.'))
    if (!Number.isInteger(qty) || qty < 0) {
      editError.value = 'Остаток должен быть целым числом ≥ 0'
      return
    }
    body.stock_qty = qty
  }

  saving.value = true
  try {
    const res = await request<ProductRow>(`/api/v1/manager/products/${editing.value.id}`, {
      method: 'PATCH',
      body,
    })
    const idx = rows.value.findIndex((r) => r.id === res.id)
    if (idx !== -1) rows.value[idx] = res
    editSuccess.value = true
    successTimer = setTimeout(closeEdit, 1200)
  } catch (e) {
    const st = getErrorStatus(e)
    if (st === 404) editError.value = 'Товар не найден (возможно, был удалён)'
    else if (st === 422) editError.value = 'Проверьте поля: цена должна быть числом ≥ 0'
    else editError.value = getErrorMessage(e, 'Не удалось сохранить изменения')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  loadBrands()
})
</script>

<template>
  <div>
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Управление каталогом</h1>
        <p class="text-sm text-ink-muted mt-1">
          <template v-if="!loading">{{ total }} товаров</template>
          <template v-else>Загрузка…</template>
        </p>
      </div>
      <NuxtLink to="/manager/import" class="btn-secondary shrink-0">
        <Icon name="heroicons:arrow-up-tray" class="w-4 h-4" /> Импортировать прайс
      </NuxtLink>
    </div>

    <!-- Фильтры -->
    <form class="card p-4 mb-6" @submit.prevent="applySearch">
      <div class="flex flex-col lg:flex-row lg:items-center gap-3">
        <div class="relative flex-1 min-w-0">
          <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
          <input
            v-model="q"
            type="search"
            placeholder="Артикул или наименование…"
            class="input pl-10"
          >
        </div>
        <select v-model="brandId" class="input lg:w-48" @change="applyFilters">
          <option value="">Все бренды</option>
          <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
        <select v-model="stock" class="input lg:w-44" @change="applyFilters">
          <option value="">Все статусы</option>
          <option value="IN_STOCK">В наличии</option>
          <option value="PREORDER">Под заказ</option>
          <option value="ARCHIVED">Архив</option>
        </select>
        <select v-model="perPage" class="input lg:w-28" @change="applyFilters">
          <option :value="20">20 / стр.</option>
          <option :value="50">50 / стр.</option>
          <option :value="100">100 / стр.</option>
        </select>
        <div class="flex gap-2 shrink-0">
          <button type="submit" class="btn-primary flex-1 lg:flex-none">Найти</button>
          <button type="button" class="btn-ghost" @click="resetFilters">Сбросить</button>
        </div>
      </div>
    </form>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 8" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0" />
    </div>

    <div v-else-if="!rows.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:cube" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>{{ appliedQ || brandId || stock ? 'По этим фильтрам товаров нет' : 'Товаров пока нет' }}</p>
    </div>

    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Артикул</th>
              <th class="px-4 py-3 font-medium">Наименование</th>
              <th class="px-4 py-3 font-medium">Бренд</th>
              <th class="px-4 py-3 font-medium">Серия</th>
              <th class="px-4 py-3 font-medium text-right">Базовая цена</th>
              <th class="px-4 py-3 font-medium text-right">Цена менеджера</th>
              <th class="px-4 py-3 font-medium text-right">Остатки</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium text-right" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in rows" :key="p.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 font-mono text-xs whitespace-nowrap">{{ p.sku }}</td>
              <td class="px-4 py-3 max-w-64 truncate" :title="p.name">{{ p.name }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ p.brand?.name || '—' }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ p.series?.name || '—' }}</td>
              <td class="px-4 py-3 text-right whitespace-nowrap">{{ formatMoney(p.base_price) }}</td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <span v-if="p.override_price !== null" class="font-semibold text-primary">{{ formatMoney(p.override_price) }}</span>
                <span v-else class="text-ink-faint">—</span>
              </td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <span v-if="p.stock_qty !== null && p.stock_qty !== undefined">{{ p.stock_qty }} шт</span>
                <span v-else class="text-ink-faint">—</span>
              </td>
              <td class="px-4 py-3">
                <span :class="STOCK_META[p.stock_status].cls">{{ STOCK_META[p.stock_status].label }}</span>
              </td>
              <td class="px-4 py-3 text-right">
                <button class="btn-outline text-xs py-1.5 px-3" @click="openEdit(p)">Изменить</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div
      v-if="!loading && rows.length"
      class="flex flex-col sm:flex-row items-center justify-between gap-4 mt-6"
    >
      <p class="text-sm text-ink-muted">Показано {{ shownFrom }}–{{ shownTo }} из {{ total }}</p>
      <nav v-if="totalPages > 1" class="flex items-center gap-1">
        <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
          <Icon name="heroicons:chevron-left" class="w-5 h-5" />
        </button>
        <button
          v-for="pgn in totalPages"
          :key="pgn"
          class="w-10 h-10 rounded-pill font-medium text-sm"
          :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
          @click="goPage(pgn)"
        >{{ pgn }}</button>
        <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
          <Icon name="heroicons:chevron-right" class="w-5 h-5" />
        </button>
      </nav>
    </div>

    <!-- Изменение товара -->
    <div
      v-if="editing"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) closeEdit(); overlayDown = false"
    >
      <form class="card max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto" @submit.prevent="submitEdit">
        <div class="flex items-start justify-between gap-4 mb-5">
          <div class="min-w-0">
            <h3 class="font-semibold">Товар {{ editing.sku }}</h3>
            <p class="text-sm text-ink-muted mt-0.5 truncate">{{ editing.name }}</p>
          </div>
          <button type="button" class="btn-ghost p-2 -mr-2 shrink-0" @click="closeEdit">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label" for="pc-override">Цена менеджера, BYN</label>
            <input
              id="pc-override"
              v-model="editPrice"
              type="number"
              min="0"
              step="0.01"
              class="input"
              placeholder="Напр. 149.90"
              :disabled="editResetPrice"
            >
            <p class="text-xs text-ink-faint mt-1.5">
              Базовая цена: {{ formatMoney(editing.base_price) }} BYN. Переопределяет базовую для всех клиентов.
            </p>
          </div>
          <label class="flex items-center gap-2.5 text-sm cursor-pointer select-none">
            <input
              v-model="editResetPrice"
              type="checkbox"
              class="w-4 h-4 accent-primary"
            >
            Сбросить цену менеджера (использовать базовую)
          </label>
          <div>
            <label class="label" for="pc-stock">Статус остатка</label>
            <select id="pc-stock" v-model="editStock" class="input">
              <option value="IN_STOCK">В наличии</option>
              <option value="PREORDER">Под заказ</option>
              <option value="ARCHIVED">Архив</option>
            </select>
          </div>
          <div>
            <label class="label" for="pc-stock-qty">Остаток, шт</label>
            <input
              id="pc-stock-qty"
              v-model="editStockQty"
              type="number"
              min="0"
              step="1"
              class="input"
              placeholder="Напр. 12 (пусто — не менять)"
            >
          </div>
        </div>

        <div v-if="editSuccess" class="badge-success w-full justify-center py-2 mt-5">Сохранено</div>
        <div v-else-if="editError" class="badge-danger w-full justify-center py-2 mt-5">{{ editError }}</div>

        <div class="flex justify-end gap-2 mt-6">
          <button type="button" class="btn-ghost" @click="closeEdit">Закрыть</button>
          <button type="submit" class="btn-primary" :disabled="saving || editSuccess">
            <span v-if="saving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ saving ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
