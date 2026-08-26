<script setup lang="ts">
// Массовое добавление по артикулам (фича B). См. SITEMAP.md §6 `/bulk-add`.
// POST /catalog/resolve-bulk (проверка) → POST /cart/items/bulk (добавление).
import type { BulkCartAddOut, BulkResolveOut, StockStatus } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Массовое добавление' })

const { request } = useApi()
const { refresh: refreshCart } = useCart()

const MAX_ITEMS = 500
// SKU, затем опционально qty через '=', таб или ';'.
const LINE_RE = /^(\S+?)(?:[=\t;]\s*(\d+))?$/

// --- Карточка 1: ввод списка ---
const text = ref('')
const resolving = ref(false)
const resolveError = ref('')

const parsed = computed<{ items: { sku: string; qty: number }[]; invalid: string[] }>(() => {
  const items: { sku: string; qty: number }[] = []
  const invalid: string[] = []
  for (const raw of text.value.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue // пустые строки и комментарии
    const m = line.match(LINE_RE)
    const qty = m?.[2] ? Number.parseInt(m[2], 10) : 1
    if (m && m[1] && qty >= 1) {
      items.push({ sku: m[1], qty })
    } else {
      invalid.push(line)
    }
  }
  return { items, invalid }
})

const overCap = computed(() => parsed.value.items.length > MAX_ITEMS)
const canCheck = computed(() => !resolving.value && parsed.value.items.length > 0 && !overCap.value)

// --- Карточка 2: результаты ---
type Row = BulkResolveOut['data'][number] & { selected: boolean }

const rows = ref<Row[]>([])
const resolved = ref(false)
const adding = ref(false)
const addError = ref('')
const addResult = ref<BulkCartAddOut | null>(null)

const foundCount = computed(() => rows.value.filter(r => r.found).length)
const selectedRows = computed(() => rows.value.filter(r => r.found && r.selected))
const selectedCount = computed(() => selectedRows.value.length)

const STOCK_META: Record<StockStatus, { label: string; cls: string }> = {
  IN_STOCK: { label: 'В наличии', cls: 'badge-success' },
  PREORDER: { label: 'Под заказ', cls: 'badge-warning' },
  ARCHIVED: { label: 'Архив', cls: 'badge-danger' },
}

async function onResolve() {
  if (!canCheck.value) return
  resolving.value = true
  resolveError.value = ''
  addError.value = ''
  addResult.value = null
  try {
    const res = await request<BulkResolveOut>('/api/v1/catalog/resolve-bulk', {
      method: 'POST',
      body: { items: parsed.value.items.slice(0, MAX_ITEMS) },
    })
    rows.value = res.data.map(r => ({ ...r, selected: r.found }))
    resolved.value = true
  } catch (e) {
    resolveError.value = getErrorMessage(e, 'Не удалось проверить артикулы')
  } finally {
    resolving.value = false
  }
}

async function addSelected() {
  if (!selectedCount.value || adding.value) return
  adding.value = true
  addError.value = ''
  try {
    const res = await request<BulkCartAddOut>('/api/v1/cart/items/bulk', {
      method: 'POST',
      body: {
        items: selectedRows.value.map(r => ({ sku: r.sku, qty: Math.max(1, Math.floor(r.qty) || 1) })),
      },
    })
    addResult.value = res
    refreshCart() // обновить счётчик корзины в шапке
  } catch (e) {
    addError.value = getErrorMessage(e, 'Не удалось добавить позиции в корзину')
  } finally {
    adding.value = false
  }
}

/** «Проверить ещё»: сбрасываем результаты, введённый список остаётся. */
function resetResults() {
  rows.value = []
  resolved.value = false
  addResult.value = null
  addError.value = ''
  resolveError.value = ''
}
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Массовое добавление</h1>
      <p class="text-sm text-ink-muted mt-1">Вставьте список артикулов из Excel или текста — проверим цены и наличие</p>
    </div>

    <div class="grid gap-6 items-start">
      <!-- Карточка 1: ввод списка -->
      <div class="card p-5">
        <label class="label" for="bulk-text">Вставьте список артикулов</label>
        <textarea
          id="bulk-text"
          v-model="text"
          rows="10"
          class="input rounded-card font-mono leading-relaxed resize-y"
          placeholder="A-100&#10;A-200=5&#10;B-301	3"
        />

        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-faint mt-2">
          <span>Одна строка = один товар; количество по умолчанию — 1.</span>
          <span class="font-mono">A-100</span>
          <span class="font-mono">A-100=5</span>
          <span class="font-mono">A-100␉5</span>
          <span>разделители: <span class="font-mono">=</span>, таб, <span class="font-mono">;</span></span>
          <span>строки с <span class="font-mono">#</span> — комментарии</span>
        </div>

        <div v-if="overCap" class="badge-warning mt-3">
          Слишком много позиций ({{ parsed.items.length }}): максимум {{ MAX_ITEMS }} — сократите список
        </div>

        <div v-if="parsed.invalid.length" class="mt-3">
          <p class="text-xs font-medium text-warning mb-1.5">Не распознано строк: {{ parsed.invalid.length }}</p>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="(l, i) in parsed.invalid.slice(0, 20)" :key="i" class="badge-warning font-mono">{{ l }}</span>
            <span v-if="parsed.invalid.length > 20" class="chip bg-canvas text-ink-muted">и ещё {{ parsed.invalid.length - 20 }}</span>
          </div>
        </div>

        <div v-if="resolveError" class="badge-danger mt-3">{{ resolveError }}</div>

        <div class="flex items-center gap-3 mt-4">
          <button class="btn-primary" :disabled="!canCheck" @click="onResolve">
            <span v-if="resolving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            <Icon v-else name="heroicons:magnifying-glass" class="w-4 h-4" />
            {{ resolving ? 'Проверка...' : 'Проверить' }}
          </button>
          <span class="text-sm text-ink-muted">
            {{ parsed.items.length ? `Позиций к проверке: ${Math.min(parsed.items.length, MAX_ITEMS)}` : 'Список пуст' }}
          </span>
        </div>
      </div>

      <!-- Карточка 2: результаты проверки -->
      <div v-if="resolved" class="card overflow-hidden">
        <div class="px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-2">
          <h3 class="font-semibold">Результаты проверки</h3>
          <p class="text-sm text-ink-muted">
            Найдено {{ foundCount }} из {{ rows.length }}<span v-if="foundCount < rows.length"> · не найдено {{ rows.length - foundCount }}</span>
          </p>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-4 py-3 font-medium w-10"/>
                <th class="px-4 py-3 font-medium">Артикул</th>
                <th class="px-4 py-3 font-medium">Наименование</th>
                <th class="px-4 py-3 font-medium text-right">Цена клиента</th>
                <th class="px-4 py-3 font-medium text-center">Кол-во</th>
                <th class="px-4 py-3 font-medium">Статус</th>
                <th class="px-4 py-3 font-medium">Ошибка</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, idx) in rows" :key="`${r.sku}-${idx}`" class="border-t border-border hover:bg-canvas/60">
                <td class="px-4 py-3">
                  <input v-model="r.selected" type="checkbox" class="rounded border-border" :disabled="!r.found" >
                </td>
                <td class="px-4 py-3 font-mono text-xs">{{ r.sku }}</td>
                <td class="px-4 py-3">{{ r.name || '—' }}</td>
                <td class="px-4 py-3 text-right whitespace-nowrap">
                  <template v-if="r.price">
                    <span v-if="r.price.has_discount" class="text-xs line-through text-ink-faint mr-1.5">{{ r.price.retail_price }}</span>
                    <span :class="r.price.has_discount ? 'font-semibold text-success' : 'font-semibold'">{{ r.price.client_price }}</span>
                    <span class="text-xs text-ink-faint ml-1">{{ r.price.currency }}</span>
                  </template>
                  <template v-else><span class="text-ink-faint">—</span></template>
                </td>
                <td class="px-4 py-3 text-center">
                  <input
                    v-model.number="r.qty"
                    type="number"
                    min="1"
                    class="input w-20 text-center py-1.5"
                    :disabled="!r.found"
                  >
                </td>
                <td class="px-4 py-3">
                  <span v-if="r.stock_status" :class="STOCK_META[r.stock_status].cls">{{ STOCK_META[r.stock_status].label }}</span>
                  <span v-else class="text-ink-faint">—</span>
                </td>
                <td class="px-4 py-3">
                  <span v-if="r.error" class="badge-danger">{{ r.error }}</span>
                  <span v-else class="text-ink-faint">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="px-5 py-4 border-t border-border flex flex-wrap items-center justify-between gap-3">
          <span class="text-sm text-ink-muted">Выбрано: {{ selectedCount }}</span>
          <button class="btn-primary" :disabled="!selectedCount || adding" @click="addSelected">
            <span v-if="adding" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
            {{ adding ? 'Добавление...' : 'Добавить выбранные в корзину' }}
          </button>
        </div>
      </div>

      <!-- Итог добавления -->
      <div v-if="addResult" class="card p-5">
        <div class="flex items-start gap-3 mb-4">
          <span class="w-9 h-9 shrink-0 rounded-pill bg-success-soft text-success flex items-center justify-center">
            <Icon name="heroicons:check" class="w-5 h-5" />
          </span>
          <div>
            <h3 class="font-semibold">Добавлено в корзину</h3>
            <p class="text-sm text-ink-muted mt-0.5">
              Позиций: {{ addResult.added.length }}<span v-if="addResult.rejected.length"> · отклонено: {{ addResult.rejected.length }}</span>
            </p>
          </div>
        </div>

        <div v-if="addResult.rejected.length" class="flex flex-col gap-1.5 mb-4">
          <div v-for="rj in addResult.rejected" :key="rj.sku" class="flex items-center gap-2 text-sm">
            <span class="font-mono text-xs">{{ rj.sku }}</span>
            <span class="badge-warning">{{ rj.reason }}</span>
          </div>
        </div>

        <div class="flex flex-wrap gap-3">
          <NuxtLink to="/cart" class="btn-primary">
            <Icon name="heroicons:shopping-cart" class="w-4 h-4" />
            Перейти в корзину
          </NuxtLink>
          <button class="btn-outline" @click="resetResults">
            <Icon name="heroicons:arrow-path" class="w-4 h-4" />
            Проверить ещё
          </button>
        </div>
      </div>

      <div v-if="addError" class="badge-danger">{{ addError }}</div>
    </div>
  </div>
</template>
