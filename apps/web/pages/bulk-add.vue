<script setup lang="ts">
import type { Money } from '~/domain/api/v2/common.schema'
import type {
  CatalogProduct,
  CatalogStockStatus,
} from '~/domain/api/v2/catalog.schema'
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
onMounted(() => {
  void cartV2.ensureLoaded().catch(() => undefined)
})
</script>

<template>
  <div data-testid="bulk-add-page">
    <PageHeading
      eyebrow="Рабочий кабинет"
      title="Массовое добавление"
      description="Вставьте список артикулов из Excel или текста — проверим цены, наличие и идентификаторы товаров."
    />

    <div class="grid gap-6 items-start">
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
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"
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
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"
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
  </div>
</template>
