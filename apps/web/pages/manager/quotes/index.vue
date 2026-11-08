<script setup lang="ts">
// Коммерческие предложения (менеджер, Э8): лента КП по всем организациям
// (CursorResponse, фильтр статуса), конструктор DRAFT (организация + позиции
// с override-ценой в BYN + срок действия), отправка/правка/удаление черновика
// (If-Match), рендер и скачивание PDF. Контракт — docs/API_V2_CONTRACT.md
// §«Quotes» (apps/api/app/api/v2/quotes.py).
import type { QuoteItemCreate, QuoteOut, QuoteStatus, QuoteSummary } from '~/domain/api/v2/quote.schema'
import { problemMessage } from '~/domain/api/v2/problem'
import { createOrganizationRepository } from '~/domain/organization/organization.repository'
import type { OrganizationSummary } from '~/domain/api/v2/organizations.schema'
import type { ManagerProductPage, ManagerProductRow } from '~/types/api'
import {
  normalizePriceInput,
  normalizeQuantityInput,
  QUOTE_STATUS_META,
  QUOTE_STATUS_TABS,
  quoteFileName,
} from '~/utils/quote'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Коммерческие предложения — Менеджер' })

const { repository, activeId: downloadActiveId, error: downloadError, downloadPdf } = useQuotes()
const orgRepository = createOrganizationRepository(useApiV2())
const { request } = useApi()
const { show } = useToast()

const LIMIT = 20

// ------------------------------------------------------------- лента КП
const loading = ref(true)
const error = ref('')
const quotes = ref<QuoteSummary[]>([])
const statusFilter = ref<'' | QuoteStatus>('')
const hasMore = ref(false)
const nextCursor = ref<string | null>(null)
const loadingMore = ref(false)
const actingId = ref<string | null>(null)
const editLoadingId = ref<string | null>(null)
const actionError = ref('')

let loadSeq = 0
let isUnmounted = false

async function load(reset = true) {
  const seq = ++loadSeq
  if (reset) loading.value = true
  else loadingMore.value = true
  error.value = ''
  try {
    const page = await repository.listManager({
      status: statusFilter.value || undefined,
      limit: LIMIT,
      cursor: reset ? undefined : (nextCursor.value ?? undefined),
    })
    if (seq !== loadSeq || isUnmounted) return
    quotes.value = reset ? page.quotes : [...quotes.value, ...page.quotes]
    nextCursor.value = page.nextCursor
    hasMore.value = page.hasMore
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    error.value = problemMessage(cause, 'Не удалось загрузить КП')
  } finally {
    if (seq === loadSeq && !isUnmounted) {
      loading.value = false
      loadingMore.value = false
    }
  }
}

function applyStatus(status: '' | QuoteStatus) {
  if (statusFilter.value === status) return
  statusFilter.value = status
  void load()
}

function toSummary(quote: QuoteOut): QuoteSummary {
  return {
    id: quote.id,
    organizationId: quote.organizationId,
    number: quote.number,
    status: quote.status,
    validUntil: quote.validUntil,
    total: quote.total,
    version: quote.version,
    createdAt: quote.createdAt,
  }
}

function replaceRow(quote: QuoteOut) {
  const index = quotes.value.findIndex((row) => row.id === quote.id)
  if (index !== -1) quotes.value[index] = toSummary(quote)
}

async function sendQuote(row: QuoteSummary) {
  if (actingId.value) return
  actingId.value = row.id
  actionError.value = ''
  try {
    const quote = await repository.send(row.id, row.version)
    // Если активен фильтр статусов — убираем карточку из текущей выборки.
    if (statusFilter.value && statusFilter.value !== quote.status) {
      quotes.value = quotes.value.filter((item) => item.id !== quote.id)
    } else {
      replaceRow(quote)
    }
    show(`КП ${quote.number} отправлено клиенту`, { type: 'success' })
  } catch (cause) {
    actionError.value = problemMessage(cause, 'Не удалось отправить КП')
  } finally {
    actingId.value = null
  }
}

async function deleteQuote(row: QuoteSummary) {
  if (actingId.value) return
  if (!window.confirm(`Удалить черновик КП${row.number ? ` ${row.number}` : ''}? Действие нельзя отменить.`)) return
  actingId.value = row.id
  actionError.value = ''
  try {
    await repository.remove(row.id, row.version)
    quotes.value = quotes.value.filter((item) => item.id !== row.id)
    show('Черновик КП удалён', { type: 'success' })
  } catch (cause) {
    actionError.value = problemMessage(cause, 'Не удалось удалить КП')
  } finally {
    actingId.value = null
  }
}

/** PDF в строке: если уже READY — сразу скачивание, иначе рендер и скачать. */
async function downloadRowPdf(row: QuoteSummary) {
  if (actingId.value || downloadActiveId.value) return
  actingId.value = row.id
  actionError.value = ''
  try {
    const { quote } = await repository.getManager(row.id)
    if (quote.pdfStatus !== 'READY') {
      const render = await repository.renderPdf(quote.id)
      if (render.pdfStatus !== 'READY') {
        actionError.value = 'PDF не удалось сформировать — попробуйте позже'
        return
      }
    }
    await downloadPdf(row.id, quoteFileName(row.number))
  } catch (cause) {
    actionError.value = problemMessage(cause, 'Не удалось подготовить PDF КП')
  } finally {
    actingId.value = null
  }
}

// --------------------------------------------------- конструктор КП (диалог)
interface DraftItem {
  productId: string
  sku: string
  name: string
  price: string
  quantity: string
  comment: string
}

const dialogOpen = ref(false)
const editing = ref<QuoteOut | null>(null)
const dialogLoading = ref(false)
const saving = ref(false)
const dialogError = ref('')

const orgs = ref<OrganizationSummary[]>([])
const orgLoading = ref(false)
const orgQuery = ref('')
const organizationId = ref('')

const items = ref<DraftItem[]>([])
const validUntil = ref('')

const productQuery = ref('')
const products = ref<ManagerProductRow[]>([])
const productLoading = ref(false)

function organizationLabel(organization: OrganizationSummary): string {
  return organization.displayName || organization.legalName
}

const selectedOrg = computed(() =>
  orgs.value.find((organization) => organization.id === organizationId.value),
)

const dialogTotal = computed(() => {
  let total = 0
  for (const item of items.value) {
    const price = normalizePriceInput(item.price)
    const quantity = normalizeQuantityInput(item.quantity)
    if (price && quantity) total += Number(price) * Number(quantity)
  }
  return total.toFixed(2)
})

async function loadOrgs() {
  orgLoading.value = true
  try {
    const page = await orgRepository.list({
      q: orgQuery.value.trim() || undefined,
      limit: 20,
    })
    orgs.value = page.organizations
  } catch (cause) {
    dialogError.value = problemMessage(cause, 'Не удалось загрузить организации')
  } finally {
    orgLoading.value = false
  }
}

/** Поиск товара — тот же менеджерский источник, что и /manager/catalog. */
async function searchProducts() {
  productLoading.value = true
  try {
    const page = await request<ManagerProductPage>('/api/v1/manager/products', {
      query: {
        q: productQuery.value.trim() || undefined,
        page: 1,
        per_page: 8,
      },
    })
    products.value = page.data
  } catch (cause) {
    dialogError.value = problemMessage(cause, 'Не удалось найти товары')
  } finally {
    productLoading.value = false
  }
}

function addProduct(row: ManagerProductRow) {
  dialogError.value = ''
  if (items.value.some((item) => item.productId === row.id)) {
    dialogError.value = `Товар ${row.sku} уже добавлен в КП`
    return
  }
  items.value.push({
    productId: row.id,
    sku: row.sku,
    name: row.name,
    price: row.override_price ?? row.base_price,
    quantity: '1',
    comment: '',
  })
}

function removeItem(index: number) {
  items.value.splice(index, 1)
}

function openCreate() {
  editing.value = null
  organizationId.value = ''
  orgQuery.value = ''
  orgs.value = []
  items.value = []
  validUntil.value = ''
  dialogError.value = ''
  productQuery.value = ''
  products.value = []
  dialogOpen.value = true
  void loadOrgs()
  void searchProducts()
}

async function openEdit(row: QuoteSummary) {
  if (actingId.value || editLoadingId.value) return
  editLoadingId.value = row.id
  actionError.value = ''
  dialogError.value = ''
  dialogLoading.value = true
  dialogOpen.value = true
  try {
    const { quote } = await repository.getManager(row.id)
    editing.value = quote
    items.value = quote.items.map((item) => ({
      productId: item.productId,
      sku: item.sku,
      name: item.name,
      price: item.unitPrice.amount,
      quantity: String(item.quantity),
      comment: item.comment ?? '',
    }))
    validUntil.value = quote.validUntil ? quote.validUntil.slice(0, 10) : ''
  } catch (cause) {
    dialogOpen.value = false
    actionError.value = problemMessage(cause, 'Не удалось загрузить КП')
  } finally {
    editLoadingId.value = null
    dialogLoading.value = false
  }
}

function validUntilIso(): string | undefined {
  // Конец выбранного дня по UTC: локальный день целиком остаётся «действителен».
  return validUntil.value ? `${validUntil.value}T23:59:59.000Z` : undefined
}

function buildPayloadItems(): QuoteItemCreate[] | null {
  const result: QuoteItemCreate[] = []
  for (const item of items.value) {
    const quantity = normalizeQuantityInput(item.quantity)
    const price = normalizePriceInput(item.price)
    if (!quantity || !price) {
      dialogError.value = `Проверьте количество и цену у позиции ${item.sku} — количество целое ≥ 1, цена больше нуля`
      return null
    }
    const comment = item.comment.trim()
    result.push({
      productId: item.productId,
      quantity,
      unitPrice: { amount: price, currency: 'BYN' },
      ...(comment ? { comment } : {}),
    })
  }
  return result
}

async function submitDialog() {
  if (saving.value) return
  dialogError.value = ''
  if (!editing.value && !organizationId.value) {
    dialogError.value = 'Выберите организацию'
    return
  }
  if (!items.value.length) {
    dialogError.value = 'Добавьте хотя бы одну позицию'
    return
  }
  const payloadItems = buildPayloadItems()
  if (!payloadItems) return

  saving.value = true
  try {
    if (editing.value) {
      const quote = await repository.edit(
        editing.value.id,
        { items: payloadItems, validUntil: validUntilIso() },
        editing.value.version,
      )
      replaceRow(quote)
      dialogOpen.value = false
      show('КП обновлено', { type: 'success' })
    } else {
      await repository.create({
        organizationId: organizationId.value,
        items: payloadItems,
        validUntil: validUntilIso(),
      })
      dialogOpen.value = false
      show('Черновик КП создан', { type: 'success' })
      await load()
    }
  } catch (cause) {
    dialogError.value = problemMessage(cause, 'Не удалось сохранить КП')
  } finally {
    saving.value = false
  }
}

onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
})

onMounted(() => void load())
</script>

<template>
  <div data-testid="manager-quotes-page">
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Коммерческие предложения"
      :description="loading ? '' : `${quotes.length} КП на странице`"
    >
      <template #actions>
        <UiButton size="touch" data-testid="manager-quotes-create" @click="openCreate">
          <template #leading><Icon name="heroicons:plus" class="size-4" /></template>
          Создать КП
        </UiButton>
      </template>
    </PageHeading>

    <!-- Фильтр статусов — кнопками, как в /manager/orders -->
    <div class="mb-6 flex flex-wrap gap-2" data-testid="manager-quotes-status-filter">
      <button
        v-for="tab in QUOTE_STATUS_TABS"
        :key="tab.value || 'all'"
        type="button"
        class="btn-outline min-h-11 px-3 text-sm"
        :class="statusFilter === tab.value ? 'border-action bg-action text-action-on' : 'bg-surface text-ink-muted hover:border-action'"
        :data-testid="`manager-quotes-status-${tab.value || 'all'}`"
        @click="applyStatus(tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <UiErrorState
      v-if="error && !quotes.length"
      class="mb-4"
      title="Не удалось загрузить КП"
      :description="error"
      data-testid="manager-quotes-error"
    >
      <template #action>
        <UiButton variant="secondary" size="compact" @click="load()">Повторить</UiButton>
      </template>
    </UiErrorState>
    <UiErrorState
      v-if="error && quotes.length"
      class="mb-4"
      title="Не удалось обновить список"
      :description="error"
      @retry="load()"
    />
    <UiErrorState
      v-if="actionError"
      class="mb-4"
      title="Действие не выполнено"
      :description="actionError"
      data-testid="manager-quotes-action-error"
    />
    <UiErrorState
      v-if="downloadError"
      class="mb-4"
      title="PDF не скачан"
      :description="downloadError"
      data-testid="manager-quotes-pdf-error"
    />

    <div
      v-if="loading"
      class="border border-border bg-surface p-4"
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-testid="manager-quotes-loading"
    >
      <span class="sr-only">Загружаем список КП…</span>
      <UiSkeleton v-for="i in 4" :key="i" class="mb-3 h-14 w-full last:mb-0" aria-hidden="true" />
    </div>

    <UiEmptyState
      v-else-if="!quotes.length && !error"
      class="border border-border bg-surface"
      title="КП пока нет"
      description="Создайте коммерческое предложение — подберите товары, задайте цены и отправьте клиенту."
      icon="heroicons:document-text"
      data-testid="manager-quotes-empty"
    />

    <div v-else class="border border-border bg-surface" data-testid="manager-quotes-table">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border bg-surface-2 text-left text-ink-muted">
              <th class="px-4 py-3 font-medium">Номер</th>
              <th class="px-4 py-3 font-medium">Организация</th>
              <th class="px-4 py-3 text-right font-medium">Сумма</th>
              <th class="px-4 py-3 font-medium">Действ. до</th>
              <th class="px-4 py-3 font-medium">Создано</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in quotes"
              :key="row.id"
              class="border-t border-border hover:bg-canvas/60"
              :data-testid="`manager-quotes-row-${row.id}`"
            >
              <td class="whitespace-nowrap px-4 py-3 font-mono text-xs" :title="row.id">
                {{ row.number ?? 'Черновик' }}
              </td>
              <td class="px-4 py-3 text-ink-muted" :title="row.organizationId">
                {{ row.organizationId.slice(0, 8) }}
              </td>
              <td class="numeric whitespace-nowrap px-4 py-3 text-right font-semibold">
                {{ formatMoney(row.total.amount, row.total.currency) }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-ink-muted">
                {{ row.validUntil ? formatDate(row.validUntil) : '—' }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-ink-muted">{{ formatDate(row.createdAt) }}</td>
              <td class="px-4 py-3">
                <UiStatusBadge
                  :tone="QUOTE_STATUS_META[row.status].tone"
                  :label="QUOTE_STATUS_META[row.status].label"
                  dot
                  :data-testid="`manager-quotes-status-${row.id}`"
                />
              </td>
              <td class="px-4 py-3 text-right">
                <div class="flex items-center justify-end gap-1.5">
                  <template v-if="row.status === 'DRAFT'">
                    <UiButton
                      size="compact"
                      :loading="actingId === row.id"
                      :disabled="actingId !== null || editLoadingId !== null"
                      :data-testid="`manager-quotes-send-${row.id}`"
                      @click="sendQuote(row)"
                    >
                      <template #leading><Icon name="heroicons:paper-airplane" class="size-4" /></template>
                      Отправить
                    </UiButton>
                    <UiButton
                      variant="secondary"
                      size="compact"
                      :loading="editLoadingId === row.id"
                      :disabled="actingId !== null || editLoadingId !== null"
                      :data-testid="`manager-quotes-edit-${row.id}`"
                      @click="openEdit(row)"
                    >
                      <template #leading><Icon name="heroicons:pencil-square" class="size-4" /></template>
                      Изменить
                    </UiButton>
                    <UiButton
                      variant="ghost"
                      size="compact"
                      :loading="actingId === row.id"
                      :disabled="actingId !== null || editLoadingId !== null"
                      :data-testid="`manager-quotes-delete-${row.id}`"
                      @click="deleteQuote(row)"
                    >
                      <template #leading><Icon name="heroicons:trash" class="size-4" /></template>
                      Удалить
                    </UiButton>
                  </template>
                  <UiButton
                    v-else
                    variant="secondary"
                    size="compact"
                    :loading="actingId === row.id || downloadActiveId === row.id"
                    :disabled="actingId !== null || downloadActiveId !== null"
                    :data-testid="`manager-quotes-pdf-${row.id}`"
                    @click="downloadRowPdf(row)"
                  >
                    <template #leading><Icon name="heroicons:document-arrow-down" class="size-4" /></template>
                    PDF
                  </UiButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="!loading && hasMore && nextCursor" class="mt-6 flex justify-center">
      <UiButton
        variant="outline"
        size="touch"
        :loading="loadingMore"
        :disabled="loadingMore"
        data-testid="manager-quotes-load-more"
        @click="load(false)"
      >
        Загрузить ещё
      </UiButton>
    </div>

    <!-- Конструктор КП: создание и правка DRAFT -->
    <UiDialog
      v-model:open="dialogOpen"
      :title="editing ? `Изменить КП${editing.number ? ` ${editing.number}` : ''}` : 'Новое коммерческое предложение'"
      description="Цены — в BYN, фиксированные: курс к КП не пересчитывается."
      :close-on-overlay="false"
      data-testid="manager-quotes-dialog"
    >
      <div v-if="dialogLoading" class="py-6 text-sm text-ink-muted" data-testid="manager-quotes-dialog-loading">
        Загружаем КП…
      </div>

      <div v-else class="space-y-5">
        <!-- Адресат — только при создании (у PATCH организация не меняется) -->
        <div v-if="!editing">
          <UiField for="quote-org-search" label="Организация">
            <div class="flex gap-2">
              <input
                id="quote-org-search"
                v-model="orgQuery"
                type="search"
                placeholder="Поиск по названию или УНП…"
                class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
                data-testid="manager-quotes-org-search"
                @keydown.enter.prevent="loadOrgs"
              >
              <UiButton variant="secondary" size="touch" :loading="orgLoading" @click="loadOrgs">Найти</UiButton>
            </div>
          </UiField>
          <div class="mt-2">
            <UiSelect
              v-model="organizationId"
              :options="orgs.map((organization) => ({ value: organization.id, label: organizationLabel(organization) }))"
              placeholder="Выберите организацию"
              data-testid="manager-quotes-org-select"
            />
            <p v-if="!orgLoading && !orgs.length" class="mt-1 text-xs text-ink-muted">
              Организации не найдены — измените условия поиска.
            </p>
            <p v-else-if="selectedOrg" class="mt-1 text-xs text-ink-muted" :title="selectedOrg.id">
              {{ selectedOrg.taxId ? `УНП ${selectedOrg.taxId} · ` : '' }}{{ selectedOrg.legalName }}
            </p>
          </div>
        </div>

        <!-- Позиции: поиск товара + строки с qty/ценой/комментарием -->
        <section aria-label="Позиции КП" class="border border-border p-3">
          <div class="flex flex-wrap items-end gap-2">
            <div class="min-w-0 flex-1">
              <UiField for="quote-product-search" label="Товар">
                <input
                  id="quote-product-search"
                  v-model="productQuery"
                  type="search"
                  placeholder="Поиск по SKU или названию…"
                  class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
                  data-testid="manager-quotes-product-search"
                  @keydown.enter.prevent="searchProducts"
                >
              </UiField>
            </div>
            <UiButton variant="secondary" size="touch" :loading="productLoading" @click="searchProducts">
              Найти
            </UiButton>
          </div>

          <ul v-if="products.length" class="mt-3 divide-y divide-border" data-testid="manager-quotes-products">
            <li v-for="product in products" :key="product.id" class="flex items-center justify-between gap-3 py-2">
              <div class="min-w-0">
                <p class="truncate text-sm font-medium text-ink">{{ product.name }}</p>
                <p class="numeric text-xs text-ink-muted">
                  {{ product.sku }} · прайс {{ formatMoney(product.override_price ?? product.base_price, 'BYN') }}
                </p>
              </div>
              <UiButton
                variant="outline"
                size="compact"
                :disabled="items.some((item) => item.productId === product.id)"
                :data-testid="`manager-quotes-add-product-${product.id}`"
                @click="addProduct(product)"
              >
                <template #leading><Icon name="heroicons:plus" class="size-4" /></template>
                Добавить
              </UiButton>
            </li>
          </ul>

          <div v-if="items.length" class="mt-4 space-y-3" data-testid="manager-quotes-items">
            <div
              v-for="(item, index) in items"
              :key="item.productId"
              class="border border-border-strong bg-surface-2 p-3"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-ink">{{ item.name }}</p>
                  <p class="numeric text-xs text-ink-muted">{{ item.sku }}</p>
                </div>
                <UiIconButton
                  label="Убрать позицию"
                  variant="ghost"
                  size="touch"
                  :data-testid="`manager-quotes-remove-item-${index}`"
                  @click="removeItem(index)"
                >
                  <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />
                </UiIconButton>
              </div>
              <div class="mt-2 grid gap-2 sm:grid-cols-3">
                <UiField :for="`quote-item-qty-${index}`" label="Кол-во">
                  <input
                    :id="`quote-item-qty-${index}`"
                    v-model="item.quantity"
                    type="number"
                    min="1"
                    step="1"
                    inputmode="numeric"
                    class="numeric block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
                    :data-testid="`manager-quotes-item-qty-${index}`"
                  >
                </UiField>
                <UiField :for="`quote-item-price-${index}`" label="Цена, BYN">
                  <input
                    :id="`quote-item-price-${index}`"
                    v-model="item.price"
                    type="number"
                    min="0.01"
                    step="0.01"
                    inputmode="decimal"
                    class="numeric block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
                    :data-testid="`manager-quotes-item-price-${index}`"
                  >
                </UiField>
                <UiField :for="`quote-item-comment-${index}`" label="Комментарий">
                  <input
                    :id="`quote-item-comment-${index}`"
                    v-model="item.comment"
                    type="text"
                    placeholder="необязательно"
                    class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
                    :data-testid="`manager-quotes-item-comment-${index}`"
                  >
                </UiField>
              </div>
            </div>
          </div>

          <p class="mt-3 text-right text-sm text-ink-muted">
            Итого: <span class="numeric font-semibold text-ink">{{ formatMoney(dialogTotal, 'BYN') }}</span>
          </p>
        </section>

        <UiField
          for="quote-valid-until"
          label="Действительно до"
          description="Необязательно. У отправленного КП без срока действия бэкенд отклонит отправку."
        >
          <UiDatePicker
            id="quote-valid-until"
            v-model="validUntil"
            align="end"
            data-testid="manager-quotes-valid-until"
          />
        </UiField>

        <p
          v-if="dialogError"
          class="badge-danger"
          role="alert"
          data-testid="manager-quotes-dialog-error"
        >
          {{ dialogError }}
        </p>
      </div>

      <template #footer>
        <UiButton variant="secondary" size="touch" :disabled="saving" @click="dialogOpen = false">
          Отмена
        </UiButton>
        <UiButton
          size="touch"
          :loading="saving"
          :disabled="dialogLoading || saving"
          data-testid="manager-quotes-submit"
          @click="submitDialog"
        >
          {{ editing ? 'Сохранить' : 'Создать' }}
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>
