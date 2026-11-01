<script setup lang="ts">
// Карточка организации (менеджер): SITEMAP §«/manager/organizations/[id]».
// Реализован блок «Реквизиты для счёта» (§6 «Счета на оплату», §16 п.40 п.4):
// УНП, юридический адрес, юр. телефон/email, банк (наименование/код/счёт).
// Сохранение — PATCH /api/v2/manager/organizations/{id} с `If-Match` по версии
// организации; 409 STALE_RESOURCE_VERSION не перетирает правки молча, а
// предлагает перечитать карточку (§6 «Concurrency»).
import type { ClientSkuMapping } from '~/domain/api/v2/client-sku.schema'
import type { CatalogProduct } from '~/domain/api/v2/catalog.schema'
import type { OrganizationDetail } from '~/domain/api/v2/organizations.schema'
import { problemMessage, toAppProblem } from '~/domain/api/v2/problem'
import { createCatalogRepository } from '~/domain/catalog/catalog.repository'
import { createOrganizationRepository } from '~/domain/organization/organization.repository'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })

const route = useRoute()
const organizations = createOrganizationRepository(useApiV2())
const invoices = useInvoiceRepository()
const catalog = createCatalogRepository(useApiV2())

const organizationId = computed(() => {
  const raw = route.params.id
  return Array.isArray(raw) ? raw[0] : raw
})

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const organization = ref<OrganizationDetail | null>(null)

const saving = ref(false)
const saveError = ref('')
const savedAt = ref(false)
const stale = ref(false)

/** Черновик формы реквизитов: пустая строка = поле не заполнено (прочерк в PDF). */
interface RequisitesForm {
  taxId: string
  legalAddress: string
  legalPhone: string
  legalEmail: string
  bankName: string
  bankCode: string
  bankAccount: string
}

const form = reactive<RequisitesForm>({
  taxId: '',
  legalAddress: '',
  legalPhone: '',
  legalEmail: '',
  bankName: '',
  bankCode: '',
  bankAccount: '',
})

useHead({
  title: computed(() =>
    organization.value ? `${organization.value.legalName} — Организация` : 'Организация',
  ),
})

function fillForm(source: OrganizationDetail) {
  form.taxId = source.taxId ?? ''
  form.legalAddress = source.legalAddress ?? ''
  form.legalPhone = source.legalPhone ?? ''
  form.legalEmail = source.legalEmail ?? ''
  form.bankName = source.bankName ?? ''
  form.bankCode = source.bankCode ?? ''
  form.bankAccount = source.bankAccount ?? ''
}

/** Пустое поле отправляем null — организация может жить без реквизитов. */
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function organizationName(value: OrganizationDetail): string {
  return value.displayName || value.legalName
}

async function load() {
  if (!organizationId.value) {
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  stale.value = false
  try {
    const snapshot = await organizations.getById(organizationId.value)
    organization.value = snapshot.organization
    fillForm(snapshot.organization)
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось загрузить организацию')
    if (problem.status === 404) notFound.value = true
    else error.value = problemMessage(cause, 'Не удалось загрузить организацию')
  } finally {
    loading.value = false
  }
}

const dirty = computed(() => {
  if (!organization.value) return false
  return (
    form.taxId !== (organization.value.taxId ?? '') ||
    form.legalAddress !== (organization.value.legalAddress ?? '') ||
    form.legalPhone !== (organization.value.legalPhone ?? '') ||
    form.legalEmail !== (organization.value.legalEmail ?? '') ||
    form.bankName !== (organization.value.bankName ?? '') ||
    form.bankCode !== (organization.value.bankCode ?? '') ||
    form.bankAccount !== (organization.value.bankAccount ?? '')
  )
})

async function save() {
  if (!organization.value || saving.value) return
  const current = organization.value
  saving.value = true
  saveError.value = ''
  savedAt.value = false
  stale.value = false
  try {
    const updated = await invoices.updateOrganizationRequisites(
      current.id,
      {
        taxId: orNull(form.taxId),
        legalAddress: orNull(form.legalAddress),
        legalPhone: orNull(form.legalPhone),
        legalEmail: orNull(form.legalEmail),
        bankName: orNull(form.bankName),
        bankCode: orNull(form.bankCode),
        bankAccount: orNull(form.bankAccount),
        version: current.version,
      },
      current.version,
    )
    organization.value = updated
    fillForm(updated)
    savedAt.value = true
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось сохранить реквизиты')
    if (problem.code === 'STALE_RESOURCE_VERSION') {
      // Реквизиты общие для всех счетов организации: конкурируют правки
      // менеджеров. Молча перетирать нельзя — предлагаем перечитать.
      stale.value = true
      saveError.value = `${problem.message}. Реквизиты уже изменены — перечитайте карточку.`
    } else {
      saveError.value = problemMessage(cause, 'Не удалось сохранить реквизиты')
    }
  } finally {
    saving.value = false
  }
}

// --- Кросс-справочник артикулов (Этап 7) -------------------------------

const skuMappingsApi = useClientSkuMappings()
const {
  mappings: skuMappingItems,
  total: skuMappingTotal,
  page: skuMappingPage,
  loading: skuMappingsLoading,
  error: skuMappingsError,
} = skuMappingsApi

const mappingQuery = ref('')
const addingMapping = ref(false)
const addMappingError = ref('')
const addMappingSaved = ref(false)

const newClientSku = ref('')
const newNote = ref('')
const productSearchQuery = ref('')
const productSearchLoading = ref(false)
const productSearchError = ref('')
const productSearchResults = ref<CatalogProduct[]>([])
const selectedProduct = ref<CatalogProduct | null>(null)

const deleteTarget = ref<ClientSkuMapping | null>(null)
const deletingMapping = ref(false)
const deleteMappingError = ref('')

/**
 * Справочник хранит только productId: имена/артикулы товаров добираем из
 * каталога пачками (best-effort, как разбор строк в bulk-add).
 */
const productInfo = ref<Record<string, { name: string; sku: string } | null>>({})
const productInfoPending = new Set<string>()

function productTitle(productId: string): string | null {
  return productInfo.value[productId]?.name ?? null
}
function productSkuLabel(productId: string): string | null {
  return productInfo.value[productId]?.sku ?? null
}

async function ensureProductInfo(productIds: string[]) {
  const missing = [...new Set(productIds)].filter(
    (id) => !(id in productInfo.value) && !productInfoPending.has(id),
  )
  missing.forEach((id) => productInfoPending.add(id))
  const BATCH = 8
  for (let offset = 0; offset < missing.length; offset += BATCH) {
    const batch = missing.slice(offset, offset + BATCH)
    const outcomes = await Promise.allSettled(
      batch.map((id) => catalog.getById(id)),
    )
    const next = { ...productInfo.value }
    outcomes.forEach((outcome, index) => {
      const id = batch[index]
      if (!id) return
      productInfoPending.delete(id)
      next[id] =
        outcome.status === 'fulfilled'
          ? {
              name: outcome.value.product.name,
              sku: outcome.value.product.sku,
            }
          : null
    })
    productInfo.value = next
  }
}

async function loadMappings(append = false) {
  if (!organizationId.value) return
  const result = await skuMappingsApi.loadList({
    organizationId: organizationId.value,
    query: mappingQuery.value.trim() || undefined,
    page: append ? skuMappingPage.value + 1 : 1,
    append,
  })
  if (result) void ensureProductInfo(result.mappings.map((m) => m.productId))
}

async function runProductSearch() {
  const q = productSearchQuery.value.trim()
  if (!q || productSearchLoading.value) return
  productSearchLoading.value = true
  productSearchError.value = ''
  try {
    const page = await catalog.search(q, { limit: 5 })
    productSearchResults.value = page.products
    if (!page.products.length) {
      productSearchError.value = 'Ничего не найдено — уточните запрос'
    }
  } catch (cause) {
    productSearchError.value = getErrorMessage(cause, 'Поиск не удался')
  } finally {
    productSearchLoading.value = false
  }
}

function chooseProduct(product: CatalogProduct) {
  selectedProduct.value = product
  productSearchError.value = ''
}

function resetMappingForm() {
  newClientSku.value = ''
  newNote.value = ''
  selectedProduct.value = null
  productSearchResults.value = []
  productSearchQuery.value = ''
}

async function addMapping() {
  const clientSku = newClientSku.value.trim()
  if (
    !organizationId.value ||
    !clientSku ||
    !selectedProduct.value ||
    addingMapping.value
  ) {
    return
  }
  addingMapping.value = true
  addMappingError.value = ''
  addMappingSaved.value = false
  try {
    await skuMappingsApi.create(
      {
        clientSku,
        productId: selectedProduct.value.id,
        note: newNote.value.trim() || undefined,
      },
      organizationId.value,
    )
    resetMappingForm()
    addMappingSaved.value = true
    await loadMappings()
  } catch (cause) {
    addMappingError.value = clientSkuProblemMessage(
      cause,
      'Не удалось добавить связку',
    )
  } finally {
    addingMapping.value = false
  }
}

function onDeleteDialogToggle(open: boolean) {
  if (!open) deleteTarget.value = null
}

async function confirmDeleteMapping() {
  const target = deleteTarget.value
  if (!target || !organizationId.value || deletingMapping.value) return
  deletingMapping.value = true
  deleteMappingError.value = ''
  try {
    await skuMappingsApi.remove(target.id, organizationId.value)
    deleteTarget.value = null
    // Убираем локально, чтобы не сбрасывать накопленные страницы.
    skuMappingItems.value = skuMappingItems.value.filter(
      (mapping) => mapping.id !== target.id,
    )
    skuMappingTotal.value = Math.max(0, skuMappingTotal.value - 1)
  } catch (cause) {
    deleteMappingError.value = clientSkuProblemMessage(
      cause,
      'Не удалось удалить связку',
    )
  } finally {
    deletingMapping.value = false
  }
}

onMounted(load)
onMounted(() => {
  void loadMappings()
})
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/manager/organizations" class="hover:text-primary">Организации</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Карточка</span>
    </nav>

    <div v-if="loading" class="space-y-4">
      <div class="skeleton h-24 w-full" />
      <div class="skeleton h-64 w-full" />
    </div>

    <UiEmptyState
      v-else-if="notFound"
      class="border border-border bg-surface"
      title="Организация не найдена"
      description="Проверьте ссылку или вернитесь к списку — возможно, организация была удалена."
      icon="heroicons:archive-box-x-mark"
    >
      <template #action>
        <NuxtLink to="/manager/organizations" class="btn-primary min-h-11 inline-flex items-center">К списку организаций</NuxtLink>
      </template>
    </UiEmptyState>

    <UiErrorState
      v-else-if="error && !organization"
      class="mb-5"
      title="Организация недоступна"
      :description="error"
    >
      <template #action>
        <UiButton variant="secondary" size="compact" @click="load">Повторить</UiButton>
      </template>
    </UiErrorState>

    <div v-else-if="organization">
      <PageHeading
        eyebrow="Организации"
        :title="organizationName(organization)"
        :description="`${organization.legalName} · ${organization.countryCode} · версия ${organization.version}`"
      >
        <template #actions>
          <UiStatusBadge
            :tone="organization.isActive ? 'success' : 'neutral'"
            :label="organization.isActive ? 'Активна' : 'Отключена'"
            dot
          />
        </template>
      </PageHeading>

      <!-- Сводка -->
      <div class="mb-5 grid gap-6 sm:grid-cols-2">
        <div class="border border-border bg-surface p-4">
          <h3 class="font-semibold mb-3">Организация</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридическое лицо</span>
            <span class="font-medium text-right">{{ organization.legalName }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">УНП</span>
            <span class="numeric font-medium">{{ organization.taxId || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Валюта</span>
            <span class="font-medium">{{ organization.defaultCurrency }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Создана</span>
            <span class="font-medium">{{ formatDateTime(organization.createdAt) }}</span>
          </div>
        </div>
        <div class="border border-border bg-surface p-4">
          <h3 class="font-semibold mb-3">Контакты</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический телефон</span>
            <span class="font-medium">{{ organization.legalPhone || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический email</span>
            <span class="font-medium">{{ organization.legalEmail || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический адрес</span>
            <span class="text-right font-medium">{{ organization.legalAddress || '—' }}</span>
          </div>
        </div>
      </div>

      <!-- Реквизиты для счёта -->
      <div class="mb-5 border border-border bg-surface p-4" data-testid="manager-organization-requisites">
        <h3 class="font-semibold mb-1">Реквизиты для счёта</h3>
        <p class="mb-3 text-xs text-ink-faint">
          Печатаются в PDF счёта на оплату. Незаполненные поля выводятся прочерком.
          Правка попадает в следующий перерендер PDF.
        </p>

        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="label" for="org-tax-id">УНП</label>
            <input id="org-tax-id" v-model="form.taxId" class="input" data-testid="manager-org-tax-id">
          </div>
          <div>
            <label class="label" for="org-legal-phone">Юридический телефон</label>
            <input id="org-legal-phone" v-model="form.legalPhone" class="input" data-testid="manager-org-legal-phone">
          </div>
          <div>
            <label class="label" for="org-legal-email">Юридический email</label>
            <input id="org-legal-email" v-model="form.legalEmail" type="email" class="input" data-testid="manager-org-legal-email">
          </div>
          <div>
            <label class="label" for="org-bank-name">Банк</label>
            <input id="org-bank-name" v-model="form.bankName" class="input" data-testid="manager-org-bank-name">
          </div>
          <div>
            <label class="label" for="org-bank-code">Код банка</label>
            <input id="org-bank-code" v-model="form.bankCode" class="input numeric" data-testid="manager-org-bank-code">
          </div>
          <div>
            <label class="label" for="org-bank-account">Расчётный счёт</label>
            <input id="org-bank-account" v-model="form.bankAccount" class="input numeric" data-testid="manager-org-bank-account">
          </div>
          <div class="sm:col-span-2">
            <label class="label" for="org-legal-address">Юридический адрес</label>
            <textarea
              id="org-legal-address"
              v-model="form.legalAddress"
              rows="2"
              class="input"
              data-testid="manager-org-legal-address"
            />
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="btn-primary min-h-11"
            :disabled="saving || !dirty"
            data-testid="manager-org-requisites-save"
            @click="save"
          >
            <span
              v-if="saving"
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin motion-reduce:animate-none"
            />
            <Icon v-else name="heroicons:check" class="w-4 h-4" />
            {{ saving ? 'Сохраняем…' : 'Сохранить реквизиты' }}
          </button>
          <span v-if="savedAt && !saveError" class="badge-success" data-testid="manager-org-requisites-saved">
            Реквизиты сохранены
          </span>
          <p class="text-xs text-ink-faint">
            Версия {{ organization.version }} сверяется при сохранении.
          </p>
        </div>

        <UiErrorState
          v-if="saveError"
          class="mt-3"
          :title="stale ? 'Реквизиты уже изменены' : 'Не удалось сохранить реквизиты'"
          :description="saveError"
          data-testid="manager-org-requisites-error"
        />
        <button
          v-if="stale"
          type="button"
          class="btn-outline mt-2 min-h-11"
          data-testid="manager-org-requisites-reload"
          @click="load"
        >
          Перечитать реквизиты
        </button>
      </div>

      <!-- Кросс-справочник артикулов (Этап 7) -->
      <div class="mb-5 border border-border bg-surface p-4" data-testid="manager-org-client-sku">
        <h3 class="font-semibold mb-1">Кросс-справочник артикулов</h3>
        <p class="mb-3 text-xs text-ink-faint">
          Связки «клиентский артикул → товар каталога». Клиент применяет их при
          массовом добавлении (режим «Мои артикулы»).
        </p>

        <!-- Форма добавления -->
        <div class="border border-border bg-surface-2 p-3 mb-4" data-testid="client-sku-add-form">
          <div class="grid gap-3 sm:grid-cols-2">
            <div>
              <label class="label" for="client-sku-new">Клиентский артикул</label>
              <input
                id="client-sku-new"
                v-model="newClientSku"
                class="input"
                placeholder="МОЙ-100"
                data-testid="client-sku-new-input"
              >
            </div>
            <div>
              <label class="label" for="client-sku-new-note">Примечание</label>
              <input
                id="client-sku-new-note"
                v-model="newNote"
                class="input"
                placeholder="необязательно"
                data-testid="client-sku-new-note"
              >
            </div>
            <div class="sm:col-span-2">
              <label class="label" for="client-sku-product-search">Товар каталога</label>
              <div class="flex flex-wrap gap-2">
                <input
                  id="client-sku-product-search"
                  v-model="productSearchQuery"
                  class="input min-w-56 flex-1"
                  placeholder="Поиск по названию или артикулу"
                  data-testid="client-sku-product-search"
                  @keydown.enter.prevent="runProductSearch"
                >
                <button
                  type="button"
                  class="btn-outline min-h-11"
                  :disabled="productSearchLoading || !productSearchQuery.trim()"
                  data-testid="client-sku-product-search-run"
                  @click="runProductSearch"
                >
                  {{ productSearchLoading ? 'Ищем…' : 'Найти' }}
                </button>
              </div>
              <p v-if="productSearchError" class="mt-1.5 text-xs font-medium text-danger-text" role="alert">
                {{ productSearchError }}
              </p>
              <div v-if="productSearchResults.length" class="mt-2 flex flex-col gap-1.5">
                <button
                  v-for="product in productSearchResults"
                  :key="product.id"
                  type="button"
                  class="flex min-h-11 items-center gap-3 border bg-surface px-3 py-1.5 text-left text-sm hover:bg-canvas"
                  :class="selectedProduct?.id === product.id ? 'border-action' : 'border-border'"
                  :data-testid="`client-sku-product-option-${product.sku}`"
                  @click="chooseProduct(product)"
                >
                  <span class="min-w-0">
                    <span class="block truncate font-semibold">{{ product.name }}</span>
                    <span class="block font-mono text-xs text-ink-faint">{{ product.sku }}</span>
                  </span>
                </button>
              </div>
            </div>
          </div>

          <p v-if="selectedProduct" class="mt-2 text-sm text-ink-muted" data-testid="client-sku-selected-product">
            Выбрано:
            <span class="font-semibold text-ink">{{ selectedProduct.name }}</span>
            <span class="ml-1 font-mono text-xs text-ink-faint">{{ selectedProduct.sku }}</span>
            <button type="button" class="ml-2 text-xs text-action underline" @click="selectedProduct = null">
              сбросить
            </button>
          </p>

          <div class="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              class="btn-primary min-h-11"
              :disabled="addingMapping || !newClientSku.trim() || !selectedProduct"
              data-testid="client-sku-add"
              @click="addMapping"
            >
              <span
                v-if="addingMapping"
                class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin motion-reduce:animate-none"
              />
              <Icon v-else name="heroicons:plus" class="w-4 h-4" />
              {{ addingMapping ? 'Добавляем…' : 'Добавить связку' }}
            </button>
            <span v-if="addMappingSaved && !addMappingError" class="badge-success" data-testid="client-sku-added">
              Связка добавлена
            </span>
          </div>
          <UiErrorState
            v-if="addMappingError"
            class="mt-3"
            title="Не удалось добавить связку"
            :description="addMappingError"
            data-testid="client-sku-add-error"
          />
        </div>

        <!-- Фильтр списка -->
        <div class="mb-3 flex flex-wrap gap-2">
          <input
            v-model="mappingQuery"
            class="input max-w-xs"
            placeholder="Поиск по артикулу или примечанию"
            data-testid="client-sku-filter"
            @keydown.enter.prevent="loadMappings()"
          >
          <UiButton
            variant="outline"
            size="touch"
            :disabled="skuMappingsLoading"
            data-testid="client-sku-refresh"
            @click="loadMappings()"
          >
            Обновить
          </UiButton>
        </div>

        <UiErrorState
          v-if="skuMappingsError && !skuMappingItems.length"
          class="mb-3"
          title="Справочник недоступен"
          :description="skuMappingsError"
          data-testid="client-sku-list-error"
        >
          <template #action>
            <UiButton variant="secondary" size="compact" @click="loadMappings()">Повторить</UiButton>
          </template>
        </UiErrorState>

        <div v-if="skuMappingsLoading && !skuMappingItems.length" class="space-y-2">
          <div class="skeleton h-10 w-full" />
          <div class="skeleton h-10 w-full" />
          <div class="skeleton h-10 w-full" />
        </div>

        <p v-else-if="!skuMappingItems.length" class="py-4 text-sm text-ink-muted" data-testid="client-sku-empty">
          Связок пока нет — добавьте первую через форму выше.
        </p>

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[640px]" data-testid="client-sku-table">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-3 py-2 font-medium">Клиентский артикул</th>
                <th class="px-3 py-2 font-medium">Товар</th>
                <th class="px-3 py-2 font-medium">Примечание</th>
                <th class="w-16 px-3 py-2 font-medium"><span class="sr-only">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="mapping in skuMappingItems"
                :key="mapping.id"
                class="border-t border-border hover:bg-canvas/60"
                :data-testid="`client-sku-mapping-${mapping.clientSku}`"
              >
                <td class="px-3 py-2 font-mono text-xs">{{ mapping.clientSku }}</td>
                <td class="px-3 py-2">
                  <template v-if="productTitle(mapping.productId)">
                    <span class="block font-medium">{{ productTitle(mapping.productId) }}</span>
                    <span class="block font-mono text-xs text-ink-faint">{{ productSkuLabel(mapping.productId) }}</span>
                  </template>
                  <span v-else class="font-mono text-xs text-ink-faint">{{ mapping.productId }}</span>
                </td>
                <td class="px-3 py-2 text-ink-muted">{{ mapping.note || '—' }}</td>
                <td class="px-3 py-2 text-right">
                  <UiButton
                    variant="danger"
                    size="compact"
                    :data-testid="`client-sku-delete-${mapping.clientSku}`"
                    @click="deleteTarget = mapping"
                  >
                    Удалить
                  </UiButton>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="skuMappingItems.length < skuMappingTotal" class="mt-3 flex justify-center">
            <UiButton
              variant="outline"
              size="compact"
              :disabled="skuMappingsLoading"
              data-testid="client-sku-more"
              @click="loadMappings(true)"
            >
              Показать ещё ({{ skuMappingItems.length }} из {{ skuMappingTotal }})
            </UiButton>
          </div>
        </div>

        <UiDialog
          :open="deleteTarget !== null"
          :title="deleteTarget ? `Удалить связку «${deleteTarget.clientSku}»?` : 'Удалить связку?'"
          description="Клиентский артикул перестанет сопоставляться с товаром при массовом добавлении. Действие нельзя отменить."
          @update:open="onDeleteDialogToggle"
          @close="onDeleteDialogToggle(false)"
        >
          <UiErrorState
            v-if="deleteMappingError"
            class="mb-4"
            title="Не удалось удалить связку"
            :description="deleteMappingError"
            data-testid="client-sku-delete-error"
          />
          <template #footer>
            <UiButton variant="outline" :disabled="deletingMapping" @click="deleteTarget = null">
              Отмена
            </UiButton>
            <UiButton
              variant="danger"
              :loading="deletingMapping"
              data-testid="client-sku-delete-confirm"
              @click="confirmDeleteMapping"
            >
              Удалить
            </UiButton>
          </template>
        </UiDialog>
      </div>
    </div>
  </div>
</template>
