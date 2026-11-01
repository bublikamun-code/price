<script setup lang="ts">
import type { Money } from '~/domain/api/v2/common.schema'
import type {
  CatalogProduct,
  CatalogStockStatus,
} from '~/domain/api/v2/catalog.schema'
import type {
  ApplyCsvRow,
  ApplyCsvSummary,
} from '~/domain/api/v2/client-sku.schema'
import { catalogProductIdSchema } from '~/domain/api/v2/catalog.schema'
import { createCatalogRepository } from '~/domain/catalog/catalog.repository'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Массовое добавление' })

const repository = createCatalogRepository(useApiV2())
const cartV2 = useCartV2()

const MAX_ITEMS = 500
const RESOLVE_BATCH_SIZE = 8
const LINE_RE = /^(\S+?)(?:[=\t;]\s*(\d+))?$/

const text = ref('')
const resolving = ref(false)
const resolveError = ref('')
const parsed = computed<{
  items: Array<{ sku: string; qty: number }>
  invalid: string[]
}>(() => {
  const items: Array<{ sku: string; qty: number }> = []
  const invalid: string[] = []
  for (const raw of text.value.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const match = line.match(LINE_RE)
    const qty = match?.[2] ? Number.parseInt(match[2], 10) : 1
    if (match && match[1] && qty >= 1) items.push({ sku: match[1], qty })
    else invalid.push(line)
  }
  return { items, invalid }
})
const overCap = computed(() => parsed.value.items.length > MAX_ITEMS)
const canCheck = computed(
  () => !resolving.value && parsed.value.items.length > 0 && !overCap.value,
)

type Row = {
  sku: string
  qty: number
  found: boolean
  productId: string | null
  name: string | null
  price: Money | null
  retailPrice: Money | null
  hasDiscount: boolean
  stockStatus: CatalogStockStatus | null
  error: string | null
  selected: boolean
}

const rows = ref<Row[]>([])
const resolved = ref(false)
const adding = ref(false)
const addError = ref('')
const addResult = ref<{
  requested: number
  succeeded: number
  failed: Array<{ productId: string; sku: string; reason: string }>
} | null>(null)

const foundCount = computed(() => rows.value.filter((row) => row.found).length)
const selectedRows = computed(() =>
  rows.value.filter((row) => row.found && row.productId && row.selected),
)
const selectedCount = computed(() => selectedRows.value.length)
const STOCK_META: Record<CatalogStockStatus, { label: string; cls: string }> = {
  IN_STOCK: { label: 'В наличии', cls: 'badge-success' },
  PREORDER: { label: 'Под заказ', cls: 'badge-warning' },
}

function money(value: Money): string {
  return formatMoney(value.amount, value.currency)
}
function rowFromProduct(
  sku: string,
  qty: number,
  product: CatalogProduct,
): Row {
  return {
    sku,
    qty,
    found: true,
    productId: product.id,
    name: product.name,
    price: product.clientPrice,
    retailPrice: product.retailPrice,
    hasDiscount: product.hasDiscount,
    stockStatus: product.stockStatus,
    error: null,
    selected: true,
  }
}
function missingRow(sku: string, qty: number, error: string): Row {
  return {
    sku,
    qty,
    found: false,
    productId: null,
    name: null,
    price: null,
    retailPrice: null,
    hasDiscount: false,
    stockStatus: null,
    error,
    selected: false,
  }
}

async function onResolve() {
  if (!canCheck.value) return
  resolving.value = true
  resolveError.value = ''
  addError.value = ''
  addResult.value = null
  const requested = parsed.value.items.slice(0, MAX_ITEMS)
  const nextRows: Row[] = []

  try {
    for (
      let offset = 0;
      offset < requested.length;
      offset += RESOLVE_BATCH_SIZE
    ) {
      const batch = requested.slice(offset, offset + RESOLVE_BATCH_SIZE)
      const outcomes = await Promise.allSettled(
        batch.map((item) => repository.getBySku(item.sku, 'fixed')),
      )
      outcomes.forEach((outcome, index) => {
        const item = batch[index]!
        if (outcome.status === 'fulfilled') {
          nextRows.push(
            rowFromProduct(item.sku, item.qty, outcome.value.product),
          )
        } else {
          nextRows.push(
            missingRow(
              item.sku,
              item.qty,
              getErrorMessage(outcome.reason, 'Товар не найден или недоступен'),
            ),
          )
        }
      })
    }
    rows.value = nextRows
    resolved.value = true
  } catch (cause) {
    resolveError.value = getErrorMessage(cause, 'Не удалось проверить артикулы')
  } finally {
    resolving.value = false
  }
}

function canonicalProductId(productId: string): string {
  return catalogProductIdSchema.parse(productId)
}
function cartQuantity(quantity: number): string {
  return String(Math.max(1, Math.floor(quantity) || 1))
}
let cartMutationQueue: Promise<unknown> = Promise.resolve()
function enqueueCartMutation<T>(operation: () => Promise<T>): Promise<T> {
  const result = cartMutationQueue.then(operation, operation)
  cartMutationQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}
async function readyCart() {
  const snapshot = await cartV2.ensureReady()
  if (!snapshot) throw new Error('Не удалось определить коммерческий контекст')
  return snapshot
}

async function addSelected() {
  const selected = [...selectedRows.value]
  if (!selected.length || adding.value) return
  adding.value = true
  addError.value = ''
  addResult.value = null
  const result = {
    requested: selected.length,
    succeeded: 0,
    failed: [] as Array<{ productId: string; sku: string; reason: string }>,
  }

  await enqueueCartMutation(async () => {
    try {
      await readyCart()
    } catch (cause) {
      const reason = getErrorMessage(cause, 'Не удалось подготовить заявку')
      result.failed = selected.map((row) => ({
        productId: row.productId!,
        sku: row.sku,
        reason,
      }))
      return
    }

    // В API v2 нет bulk-эндпоинта. Позиции добавляются строго последовательно,
    // чтобы каждый POST получил актуальный ETag предыдущего изменения.
    for (const row of selected) {
      try {
        const productId = canonicalProductId(row.productId!)
        await cartV2.addItem({
          productId,
          quantity: cartQuantity(row.qty),
        })
        row.selected = false
        result.succeeded += 1
      } catch (cause) {
        result.failed.push({
          productId: row.productId!,
          sku: row.sku,
          reason: getErrorMessage(cause, 'Не удалось добавить позицию'),
        })
      }
    }
  })

  if (!result.succeeded) {
    addError.value =
      'Ни одну позицию не удалось добавить. Исправьте отмеченные ошибки и повторите.'
  }
  addResult.value = result
  adding.value = false
}

function resetResults() {
  rows.value = []
  resolved.value = false
  addResult.value = null
  addError.value = ''
  resolveError.value = ''
}
watch(text, () => {
  if (resolved.value) resetResults()
})

// ---------------------------------------------------------------------------
// Режим «Мои артикулы» (Этап 7): кросс-справочник клиентских артикулов.
// Тот же CSV-парсер, что и у «наших артикулов» (LINE_RE выше), но проверка
// идёт через POST /apply-csv — бэк сам сопоставляет связки, добавляет найденное
// в заявку и возвращает построчный отчёт.
// ---------------------------------------------------------------------------

type ClientApplyStatus = 'MATCHED' | 'UNKNOWN' | 'AMBIGUOUS'

type ClientRow = {
  clientSku: string
  qty: number
  status: ClientApplyStatus
  productId: string | null
  productName: string | null
  productSku: string | null
  unitPrice: Money | null
  // Бэк отдаёт строкой (StockStatus); неизвестные значения — прочерк.
  stockStatus: string | null
  message: string | null
  // Связка запомнена локально (строка UNKNOWN после inline-поиска):
  savedProductId: string | null
  savedProductSku: string | null
  savedProductName: string | null
  addingToCart: boolean
  addedToCart: boolean
  addError: string | null
}

const mode = ref<'catalog' | 'client'>('catalog')
const modeOptions = [
  { value: 'catalog', label: 'Наши артикулы' },
  { value: 'client', label: 'Мои артикулы' },
]

const sessionContext = useSessionContext()
const mappingsApi = useClientSkuMappings()

const activeOrganizationId = computed(
  () => sessionContext.store.context?.organizationId ?? null,
)
// Контекст мог не долететь (сеть) — считаем режим «готовым» и показываем
// подсказку вместо вечного скелета.
const contextReady = computed(
  () => sessionContext.store.loaded || Boolean(sessionContext.store.error),
)

const CLIENT_STATUS_META: Record<
  ClientApplyStatus,
  { label: string; tone: 'info' | 'warning' | 'danger' }
> = {
  MATCHED: { label: 'Найдено', tone: 'info' },
  UNKNOWN: { label: 'Нет связки', tone: 'warning' },
  AMBIGUOUS: { label: 'Дубль в списке', tone: 'danger' },
}

const clientText = ref('')
const applying = ref(false)
const applyError = ref('')
const clientRows = ref<ClientRow[]>([])
const clientSummary = ref<ApplyCsvSummary | null>(null)

const clientStats = computed(() => {
  const rows = clientRows.value
  return {
    matched: rows.filter((row) => row.status === 'MATCHED').length,
    unknown: rows.filter(
      (row) => row.status === 'UNKNOWN' && !row.savedProductId,
    ).length,
    ambiguous: rows.filter((row) => row.status === 'AMBIGUOUS').length,
    saved: rows.filter((row) => row.savedProductId && !row.addedToCart).length,
    added: rows.filter((row) => row.addedToCart).length,
  }
})

function clientRowFromApi(row: ApplyCsvRow): ClientRow {
  return {
    clientSku: row.clientSku,
    qty: row.qty,
    status: row.status,
    productId: row.productId ?? null,
    productName: row.productName ?? null,
    productSku: row.productSku ?? null,
    unitPrice: row.unitPrice ?? null,
    stockStatus: row.stockStatus ?? null,
    message: row.message ?? null,
    savedProductId: null,
    savedProductSku: null,
    savedProductName: null,
    addingToCart: false,
    addedToCart: false,
    addError: null,
  }
}

/** Толерантно к незнакомым значениям StockStatus с бэка. */
function clientStockMeta(status: string | null): { label: string; cls: string } | null {
  if (!status || !(status in STOCK_META)) return null
  return STOCK_META[status as CatalogStockStatus]
}

async function applyClientCsv() {
  const csv = clientText.value
  if (applying.value || !csv.trim()) return
  applying.value = true
  applyError.value = ''
  try {
    const result = await mappingsApi.applyCsv(csv)
    clientRows.value = result.rows.map(clientRowFromApi)
    clientSummary.value = result.summary
  } catch (cause) {
    applyError.value = clientSkuProblemMessage(
      cause,
      'Не удалось применить список',
    )
  } finally {
    applying.value = false
  }
}

// Inline-поиск товара для строки UNKNOWN: открыт максимум один поиск за раз.
const activeSearch = reactive<{
  index: number | null
  q: string
  loading: boolean
  error: string
  results: CatalogProduct[]
  selectedId: string
}>({ index: null, q: '', loading: false, error: '', results: [], selectedId: '' })

const savingMapping = ref(false)

function openRowSearch(index: number) {
  activeSearch.index = index
  activeSearch.q = clientRows.value[index]?.clientSku ?? ''
  activeSearch.results = []
  activeSearch.selectedId = ''
  activeSearch.error = ''
  activeSearch.loading = false
  // Сразу ищем по клиентскому артикулу — частый случай точного совпадения SKU.
  void searchForRow()
}
function closeRowSearch() {
  activeSearch.index = null
}

async function searchForRow() {
  const q = activeSearch.q.trim()
  if (!q || activeSearch.loading || activeSearch.index === null) return
  activeSearch.loading = true
  activeSearch.error = ''
  try {
    const page = await repository.search(q, { limit: 5 })
    activeSearch.results = page.products
    activeSearch.selectedId =
      page.products.length === 1 ? page.products[0]!.id : ''
    if (!page.products.length) {
      activeSearch.error = 'Ничего не найдено — уточните запрос'
    }
  } catch (cause) {
    activeSearch.error = getErrorMessage(cause, 'Поиск не удался')
  } finally {
    activeSearch.loading = false
  }
}

/**
 * Запомнить связку {clientSku → productId}. После успеха строка помечается
 * локально (без повторного apply-csv: тот добавил бы всё в заявку повторно) —
 * позицию добавляет кнопка в строке через обычный POST корзины.
 */
async function saveMapping(index: number) {
  const row = clientRows.value[index]
  if (!row || !activeSearch.selectedId || savingMapping.value) return
  savingMapping.value = true
  activeSearch.error = ''
  try {
    await mappingsApi.create({
      clientSku: row.clientSku,
      productId: activeSearch.selectedId,
    })
    const product = activeSearch.results.find(
      (item) => item.id === activeSearch.selectedId,
    )
    row.savedProductId = activeSearch.selectedId
    row.savedProductSku = product?.sku ?? null
    row.savedProductName = product?.name ?? null
    closeRowSearch()
  } catch (cause) {
    activeSearch.error = clientSkuProblemMessage(
      cause,
      'Не удалось сохранить связку',
    )
  } finally {
    savingMapping.value = false
  }
}

// Добавление сохранённой строки в заявку — тем же путём, что и «наши
// артикулы»: последовательные мутации корзины с актуальным ETag.
async function addSavedRow(row: ClientRow) {
  if (!row.savedProductId || row.addedToCart || row.addingToCart) return
  row.addingToCart = true
  row.addError = null
  await enqueueCartMutation(async () => {
    try {
      await readyCart()
      await cartV2.addItem({
        productId: canonicalProductId(row.savedProductId!),
        quantity: cartQuantity(row.qty),
      })
      row.addedToCart = true
    } catch (cause) {
      row.addError = getErrorMessage(cause, 'Не удалось добавить позицию')
    } finally {
      row.addingToCart = false
    }
  })
}

onMounted(() => {
  void cartV2.ensureLoaded().catch(() => undefined)
  void sessionContext.ensureLoaded().catch(() => undefined)
})
</script>

<template>
  <div data-testid="bulk-add-page">
    <PageHeading
      eyebrow="Рабочий кабинет"
      title="Массовое добавление"
      description="Вставьте список артикулов из Excel или текста — проверим цены, наличие и идентификаторы товаров."
    />

    <div class="mb-5" data-testid="bulk-add-mode">
      <UiSegmentedControl
        v-model="mode"
        :options="modeOptions"
        label="Режим массового добавления"
      />
    </div>

    <div v-if="mode === 'catalog'" class="grid gap-6 items-start">
      <div class="border-y border-border bg-surface px-4 py-5 sm:px-5">
        <label class="label" for="bulk-text">Вставьте список артикулов</label>
        <textarea
          id="bulk-text"
          v-model="text"
          rows="10"
          class="input min-h-44 font-mono leading-relaxed resize-y"
          placeholder="A-100&#10;A-200=5&#10;B-301	3"
          data-testid="bulk-add-input"
        />

        <div
          class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-faint mt-2"
        >
          <span>Одна строка = один товар; количество по умолчанию — 1.</span>
          <span class="font-mono">A-100</span>
          <span class="font-mono">A-100=5</span>
          <span class="font-mono">A-100␉5</span>
          <span
            >разделители: <span class="font-mono">=</span>, таб,
            <span class="font-mono">;</span></span
          >
          <span>строки с <span class="font-mono">#</span> — комментарии</span>
        </div>

        <div v-if="overCap" class="badge-warning mt-3" role="alert">
          Слишком много позиций ({{ parsed.items.length }}): максимум
          {{ MAX_ITEMS }} — сократите список
        </div>
        <div v-if="parsed.invalid.length" class="mt-3">
          <p class="text-xs font-medium text-warning mb-1.5">
            Не распознано строк: {{ parsed.invalid.length }}
          </p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="(line, index) in parsed.invalid.slice(0, 20)"
              :key="index"
              class="badge-warning font-mono"
              >{{ line }}</span
            >
            <span
              v-if="parsed.invalid.length > 20"
              class="chip bg-canvas text-ink-muted"
              >и ещё {{ parsed.invalid.length - 20 }}</span
            >
          </div>
        </div>
        <div v-if="resolveError" class="badge-danger mt-3" role="alert">
          {{ resolveError }}
        </div>

        <div class="flex flex-wrap items-center gap-3 mt-4">
          <button
            class="btn-primary min-h-11 inline-flex"
            :disabled="!canCheck"
            data-testid="bulk-add-resolve"
            @click="onResolve"
          >
            <span
              v-if="resolving"
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin motion-reduce:animate-none"
            />
            <Icon v-else name="heroicons:magnifying-glass" class="w-4 h-4" />
            {{ resolving ? 'Проверка…' : 'Проверить' }}
          </button>
          <span class="text-sm text-ink-muted">
            {{
              parsed.items.length
                ? `Позиций к проверке: ${Math.min(parsed.items.length, MAX_ITEMS)}`
                : 'Список пуст'
            }}
          </span>
        </div>
      </div>

      <div
        v-if="resolved"
        class="record-list overflow-hidden"
        data-testid="bulk-add-results"
      >
        <div
          class="px-4 sm:px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-2"
        >
          <h2 class="font-semibold">Результаты проверки</h2>
          <p class="text-sm text-ink-muted" aria-live="polite">
            Найдено {{ foundCount }} из {{ rows.length
            }}<template v-if="foundCount < rows.length">
              · не найдено {{ rows.length - foundCount }}</template
            >
          </p>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[760px]">
            <thead>
              <tr
                class="text-ink-muted text-left bg-surface-2 border-b border-border"
              >
                <th class="px-4 py-3 font-medium w-10">
                  <span class="sr-only">Выбрать</span>
                </th>
                <th class="px-4 py-3 font-medium">Артикул</th>
                <th class="px-4 py-3 font-medium">Наименование</th>
                <th class="px-4 py-3 font-medium text-right">Цена клиента</th>
                <th class="px-4 py-3 font-medium text-center">Кол-во</th>
                <th class="px-4 py-3 font-medium">Статус</th>
                <th class="px-4 py-3 font-medium">Ошибка</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in rows"
                :key="`${row.sku}-${index}`"
                class="border-t border-border hover:bg-canvas/60"
                :data-testid="`bulk-add-row-${index}`"
              >
                <td class="px-2 py-1">
                  <label class="flex size-11 items-center justify-center">
                    <input
                      v-model="row.selected"
                      type="checkbox"
                      class="size-5 rounded border-border"
                      :disabled="!row.found"
                      :aria-label="`Выбрать товар ${row.sku}`"
                    >
                  </label>
                </td>
                <td class="px-4 py-3 font-mono text-xs">{{ row.sku }}</td>
                <td class="px-4 py-3">{{ row.name || '—' }}</td>
                <td class="px-4 py-3 text-right whitespace-nowrap">
                  <template v-if="row.price">
                    <span
                      v-if="row.hasDiscount && row.retailPrice"
                      class="text-xs line-through text-ink-faint mr-1.5"
                      >{{ money(row.retailPrice) }}</span
                    >
                    <span class="font-semibold text-success">{{
                      money(row.price)
                    }}</span>
                  </template>
                  <template v-else
                    ><span class="text-ink-faint">—</span></template
                  >
                </td>
                <td class="px-4 py-3 text-center">
                  <div
                    class="inline-flex min-h-11 items-center border border-border rounded-control overflow-hidden bg-surface"
                  >
                    <button
                      class="flex size-11 items-center justify-center text-ink-muted hover:text-ink disabled:opacity-40"
                      :disabled="!row.found || row.qty <= 1"
                      :aria-label="`Уменьшить количество товара ${row.sku}`"
                      @click="row.qty = Math.max(1, row.qty - 1)"
                    >
                      <Icon name="heroicons:minus" class="w-3.5 h-3.5" />
                    </button>
                    <label :for="`bulk-quantity-${index}`" class="sr-only"
                      >Количество товара {{ row.sku }}</label
                    >
                    <input
                      :id="`bulk-quantity-${index}`"
                      v-model.number="row.qty"
                      type="number"
                      inputmode="numeric"
                      min="1"
                      class="h-11 w-14 text-center bg-transparent text-sm outline-none"
                      :disabled="!row.found"
                      :data-testid="`bulk-quantity-${index}`"
                    >
                    <button
                      class="flex size-11 items-center justify-center text-ink-muted hover:text-ink"
                      :disabled="!row.found"
                      :aria-label="`Увеличить количество товара ${row.sku}`"
                      @click="row.qty += 1"
                    >
                      <Icon name="heroicons:plus" class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <span
                    v-if="row.stockStatus"
                    :class="STOCK_META[row.stockStatus].cls"
                    >{{ STOCK_META[row.stockStatus].label }}</span
                  >
                  <span v-else class="text-ink-faint">—</span>
                </td>
                <td class="px-4 py-3 max-w-xs">
                  <span
                    v-if="row.error"
                    class="badge-danger whitespace-normal"
                    >{{ row.error }}</span
                  >
                  <span v-else class="text-ink-faint">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div
          class="px-4 sm:px-5 py-4 border-t border-border flex flex-wrap items-center justify-between gap-3"
        >
          <span class="text-sm text-ink-muted"
            >Выбрано: {{ selectedCount }}</span
          >
          <button
            class="btn-primary min-h-11 inline-flex"
            :disabled="!selectedCount || adding"
            data-testid="bulk-add-submit"
            @click="addSelected"
          >
            <span
              v-if="adding"
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin motion-reduce:animate-none"
            />
            <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
            {{ adding ? 'Добавление…' : 'Добавить выбранные в заявку' }}
          </button>
        </div>
      </div>

      <div v-if="addResult" class="border-y border-border bg-surface-2 p-5" data-testid="bulk-add-result">
        <div class="flex items-start gap-3 mb-4">
          <span
            class="flex size-11 shrink-0 items-center justify-center border border-border"
            :class="
              addResult.failed.length
                ? 'bg-warning-soft text-warning'
                : 'bg-success-soft text-success'
            "
          >
            <Icon
              :name="
                addResult.failed.length
                  ? 'heroicons:exclamation-triangle'
                  : 'heroicons:check'
              "
              class="w-5 h-5"
            />
          </span>
          <div>
            <h2 class="font-semibold">
              {{
                addResult.failed.length
                  ? 'Массовое добавление завершено частично'
                  : 'Добавлено в заявку'
              }}
            </h2>
            <p class="text-sm text-ink-muted mt-0.5">
              Добавлено {{ addResult.succeeded }} из {{ addResult.requested
              }}<template v-if="addResult.failed.length">
                · не добавлено: {{ addResult.failed.length }}</template
              >
            </p>
          </div>
        </div>

        <ul v-if="addResult.failed.length" class="flex flex-col gap-1.5 mb-4">
          <li
            v-for="failure in addResult.failed"
            :key="failure.productId"
            class="flex flex-wrap items-center gap-2 text-sm"
          >
            <span class="font-mono text-xs">{{ failure.sku }}</span>
            <span class="badge-warning">{{ failure.reason }}</span>
          </li>
        </ul>

        <div class="flex flex-wrap gap-3">
          <NuxtLink to="/cart" class="btn-primary min-h-11 inline-flex">
            <Icon name="heroicons:shopping-cart" class="w-4 h-4" />
            Перейти в заявку
          </NuxtLink>
          <button class="btn-outline min-h-11 inline-flex" @click="resetResults">
            <Icon name="heroicons:arrow-path" class="w-4 h-4" />
            Проверить ещё
          </button>
        </div>
      </div>

      <div
        v-if="addError"
        class="badge-danger w-full justify-center py-3"
        role="alert"
        data-testid="bulk-add-error"
      >
        {{ addError }}
      </div>
    </div>

    <div
      v-else
      class="grid gap-6 items-start"
      data-testid="bulk-add-client-mode"
    >
      <div v-if="!contextReady" class="skeleton h-40 w-full" />

      <div
        v-else-if="!activeOrganizationId"
        class="border-y border-border bg-surface px-4 py-5 sm:px-5"
        data-testid="client-sku-org-hint"
      >
        <div class="flex items-start gap-3">
          <span
            class="flex size-11 shrink-0 items-center justify-center border border-border bg-surface-2 text-ink-muted"
          >
            <Icon name="heroicons:building-office-2" class="w-5 h-5" />
          </span>
          <div>
            <h2 class="font-semibold">Доступно в контексте организации</h2>
            <p class="mt-1 text-sm text-ink-muted">
              «Мои артикулы» — кросс-справочник клиентских артикулов.
              Переключитесь на организацию, чтобы применять свои артикулы к
              каталогу и пополнять связки.
            </p>
          </div>
        </div>
      </div>

      <template v-else>
        <div class="border-y border-border bg-surface px-4 py-5 sm:px-5">
          <label class="label" for="client-sku-text"
            >Вставьте список ваших артикулов</label
          >
          <textarea
            id="client-sku-text"
            v-model="clientText"
            rows="10"
            class="input min-h-44 font-mono leading-relaxed resize-y"
            placeholder="МОЙ-100&#10;МОЙ-200=5&#10;МОЙ-301	3"
            data-testid="client-sku-csv-input"
          />

          <div
            class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-faint mt-2"
          >
            <span>Одна строка = один товар; количество по умолчанию — 1.</span>
            <span class="font-mono">МОЙ-100</span>
            <span class="font-mono">МОЙ-100=5</span>
            <span class="font-mono">МОЙ-100␉5</span>
            <span
              >разделители: <span class="font-mono">=</span>, таб,
              <span class="font-mono">;</span></span
            >
            <span>строки с <span class="font-mono">#</span> — комментарии</span>
          </div>

          <div
            v-if="applyError"
            class="badge-danger mt-3"
            role="alert"
            data-testid="client-sku-error"
          >
            {{ applyError }}
          </div>

          <div class="flex flex-wrap items-center gap-3 mt-4">
            <button
              class="btn-primary min-h-11 inline-flex"
              :disabled="applying || !clientText.trim()"
              data-testid="client-sku-apply"
              @click="applyClientCsv"
            >
              <span
                v-if="applying"
                class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin motion-reduce:animate-none"
              />
              <Icon v-else name="heroicons:magnifying-glass" class="w-4 h-4" />
              {{ applying ? 'Применяем…' : 'Применить' }}
            </button>
            <span class="text-sm text-ink-muted">
              Найденные позиции добавляются в заявку автоматически.
            </span>
          </div>
        </div>

        <div
          v-if="clientSummary"
          class="record-list overflow-hidden"
          data-testid="client-sku-report"
        >
          <div
            class="px-4 sm:px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-2"
          >
            <h2 class="font-semibold">Отчёт применения</h2>
            <p class="text-sm text-ink-muted" aria-live="polite" data-testid="client-sku-summary">
              {{ clientStats.matched }} найдено · {{ clientStats.unknown }} без
              связки · {{ clientStats.ambiguous }} дублей · добавлено в заявку:
              {{ (clientSummary?.cartAdded ?? 0) + clientStats.added }}
            </p>
          </div>

          <div
            v-if="clientStats.saved"
            class="px-4 sm:px-5 py-3 border-b border-border bg-surface-2 text-sm text-ink-muted"
          >
            Запомнено новых связок: {{ clientStats.saved }} — добавьте их в
            заявку кнопкой «В заявку» в строке.
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-sm min-w-[880px]">
              <thead>
                <tr
                  class="text-ink-muted text-left bg-surface-2 border-b border-border"
                >
                  <th class="px-4 py-3 font-medium">Артикул</th>
                  <th class="px-4 py-3 font-medium text-center">Кол-во</th>
                  <th class="px-4 py-3 font-medium">Статус</th>
                  <th class="px-4 py-3 font-medium">Товар</th>
                  <th class="px-4 py-3 font-medium text-right">Цена</th>
                  <th class="px-4 py-3 font-medium">Остаток</th>
                  <th class="px-4 py-3 font-medium">Связка</th>
                </tr>
              </thead>
              <tbody>
                <template
                  v-for="(row, index) in clientRows"
                  :key="`${row.clientSku}-${index}`"
                >
                  <tr
                    class="border-t border-border hover:bg-canvas/60"
                    :data-testid="`client-sku-row-${index}`"
                  >
                    <td class="px-4 py-3 font-mono text-xs">
                      {{ row.clientSku }}
                    </td>
                    <td class="px-4 py-3 text-center">{{ row.qty }}</td>
                    <td class="px-4 py-3">
                      <UiStatusBadge
                        :tone="CLIENT_STATUS_META[row.status].tone"
                        :label="CLIENT_STATUS_META[row.status].label"
                      />
                      <span
                        v-if="row.message"
                        class="mt-1 block max-w-48 text-xs text-ink-faint whitespace-normal"
                        >{{ row.message }}</span
                      >
                    </td>
                    <td class="px-4 py-3 max-w-xs">
                      <template v-if="row.productSku || row.productName">
                        <NuxtLink
                          v-if="row.productSku"
                          :to="`/catalog/${encodeURIComponent(row.productSku)}`"
                          class="text-sm font-semibold text-ink hover:text-action"
                          :data-testid="`client-sku-product-${index}`"
                          >{{ row.productName || row.productSku }}</NuxtLink
                        >
                        <span v-else class="text-sm">{{ row.productName }}</span>
                        <span
                          v-if="row.productSku"
                          class="block font-mono text-xs text-ink-faint"
                          >{{ row.productSku }}</span
                        >
                      </template>
                      <template
                        v-else-if="row.savedProductSku || row.savedProductName"
                      >
                        <span class="text-sm">{{
                          row.savedProductName || row.savedProductSku
                        }}</span>
                        <span
                          v-if="row.savedProductSku"
                          class="block font-mono text-xs text-ink-faint"
                          >{{ row.savedProductSku }}</span
                        >
                      </template>
                      <span v-else class="text-ink-faint">—</span>
                    </td>
                    <td class="px-4 py-3 text-right whitespace-nowrap">
                      <template v-if="row.unitPrice">
                        <span class="font-semibold text-success">{{
                          money(row.unitPrice)
                        }}</span>
                      </template>
                      <template v-else>
                        <span class="text-ink-faint">—</span>
                      </template>
                    </td>
                    <td class="px-4 py-3">
                      <span
                        v-if="clientStockMeta(row.stockStatus)"
                        :class="clientStockMeta(row.stockStatus)?.cls"
                        >{{ clientStockMeta(row.stockStatus)?.label }}</span
                      >
                      <span v-else class="text-ink-faint">—</span>
                    </td>
                    <td class="px-4 py-3">
                      <button
                        v-if="row.status === 'UNKNOWN' && !row.savedProductId"
                        type="button"
                        class="btn-outline min-h-9 inline-flex"
                        :data-testid="`client-sku-find-${index}`"
                        @click="openRowSearch(index)"
                      >
                        <Icon
                          name="heroicons:magnifying-glass"
                          class="w-4 h-4"
                        />
                        Найти
                      </button>
                      <template v-else-if="row.savedProductId">
                        <span class="badge-success">Связка сохранена</span>
                        <button
                          v-if="!row.addedToCart"
                          type="button"
                          class="btn-primary min-h-9 mt-1.5 inline-flex"
                          :disabled="row.addingToCart"
                          :data-testid="`client-sku-add-${index}`"
                          @click="addSavedRow(row)"
                        >
                          <Icon
                            name="heroicons:shopping-cart"
                            class="w-4 h-4"
                          />
                          В заявку
                        </button>
                        <span v-else class="badge-success mt-1.5">В заявке</span>
                      </template>
                      <span v-else class="text-ink-faint">—</span>
                      <span
                        v-if="row.addError"
                        class="badge-danger mt-1.5 whitespace-normal"
                        role="alert"
                        >{{ row.addError }}</span
                      >
                    </td>
                  </tr>

                  <tr
                    v-if="activeSearch.index === index"
                    class="border-t border-border bg-canvas/40"
                  >
                    <td
                      colspan="7"
                      class="px-4 py-4"
                      :data-testid="`client-sku-search-${index}`"
                    >
                      <label
                        class="label"
                        :for="`client-sku-search-input-${index}`"
                      >
                        Товар для артикула
                        <span class="font-mono">{{ row.clientSku }}</span>
                      </label>
                      <div class="flex flex-wrap gap-2">
                        <input
                          :id="`client-sku-search-input-${index}`"
                          v-model="activeSearch.q"
                          class="input min-w-56 flex-1"
                          placeholder="Поиск по каталогу"
                          :data-testid="`client-sku-search-query-${index}`"
                          @keydown.enter.prevent="searchForRow"
                        >
                        <button
                          type="button"
                          class="btn-outline min-h-11"
                          :disabled="activeSearch.loading || !activeSearch.q.trim()"
                          data-testid="client-sku-search-run"
                          @click="searchForRow"
                        >
                          <span
                            v-if="activeSearch.loading"
                            class="w-4 h-4 border-2 border-ink-muted/40 border-t-ink-muted rounded-full animate-spin motion-reduce:animate-none"
                          />
                          <Icon
                            v-else
                            name="heroicons:magnifying-glass"
                            class="w-4 h-4"
                          />
                          Найти
                        </button>
                      </div>
                      <p
                        v-if="activeSearch.error"
                        class="mt-1.5 text-xs font-medium text-danger-text"
                        role="alert"
                      >
                        {{ activeSearch.error }}
                      </p>

                      <div
                        v-if="activeSearch.results.length"
                        class="mt-3 flex flex-col gap-1.5"
                      >
                        <label
                          v-for="product in activeSearch.results"
                          :key="product.id"
                          class="flex min-h-11 cursor-pointer items-center gap-3 border bg-surface px-3 py-1.5 text-sm hover:bg-surface-2"
                          :class="
                            activeSearch.selectedId === product.id
                              ? 'border-action'
                              : 'border-border'
                          "
                        >
                          <input
                            v-model="activeSearch.selectedId"
                            type="radio"
                            name="client-sku-search-result"
                            :value="product.id"
                            class="size-5 shrink-0"
                            :data-testid="`client-sku-search-option-${product.id}`"
                            :aria-label="`Выбрать ${product.name}`"
                          >
                          <span class="min-w-0">
                            <span class="block truncate font-semibold">{{
                              product.name
                            }}</span>
                            <span
                              class="block font-mono text-xs text-ink-faint"
                              >{{ product.sku }}</span
                            >
                          </span>
                        </label>
                      </div>

                      <div class="mt-3 flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          class="btn-primary min-h-11 inline-flex"
                          :disabled="!activeSearch.selectedId || savingMapping"
                          :data-testid="`client-sku-save-${index}`"
                          @click="saveMapping(index)"
                        >
                          <Icon name="heroicons:bookmark" class="w-4 h-4" />
                          Запомнить связку
                        </button>
                        <button
                          type="button"
                          class="btn-outline min-h-11 inline-flex"
                          @click="closeRowSearch"
                        >
                          Отмена
                        </button>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
