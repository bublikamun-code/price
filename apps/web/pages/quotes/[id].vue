<script setup lang="ts">
// Карточка КП клиента (Э8): позиции и суммы — только чтение; решение по
// SENT — «Принять» (→ заявка, Idempotency-Key на операцию, delivery как в
// checkout: самовывоз или доставка с адресом из книги адресов) и
// «Отказаться» (confirm). PDF скачивается байтами, когда готов (§16 п.37).
import type { QuoteOut } from '~/domain/api/v2/quote.schema'
import type { OrganizationAddress } from '~/domain/api/v2/organizations.schema'
import { AppProblem, problemMessage } from '~/domain/api/v2/problem'
import { newIdempotencyKey } from '~/utils/idempotency-key'
import { QUOTE_PDF_STATUS_META, QUOTE_STATUS_META, quoteFileName } from '~/utils/quote'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const { repository, activeId: downloadActiveId, error: downloadError, downloadPdf } = useQuotes()
const { listAddresses, createAddress } = useOrganizationAddresses()

const STATUS_META = QUOTE_STATUS_META

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const quote = ref<QuoteOut | null>(null)
let loadSeq = 0
let isUnmounted = false
let isMounted = false

useHead({
  title: computed(() => (quote.value ? `КП ${quote.value.number ?? ''}` : 'Коммерческое предложение')),
})

const downloadable = computed(() => quote.value?.pdfStatus === 'READY')
const canDecide = computed(() => quote.value?.status === 'SENT')

function numberLabel(): string {
  return quote.value?.number ?? 'Без номера'
}

async function load() {
  const seq = ++loadSeq
  const quoteId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  if (!quoteId) {
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  quote.value = null
  try {
    const snapshot = await repository.getClient(quoteId)
    if (seq !== loadSeq || isUnmounted) return
    quote.value = snapshot.quote
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    if (cause instanceof AppProblem && cause.status === 404) notFound.value = true
    else error.value = problemMessage(cause, 'Не удалось загрузить КП')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }
}

function download() {
  if (!quote.value || !downloadable.value || downloadActiveId.value) return
  void downloadPdf(quote.value.id, quoteFileName(quote.value.number))
}

// ------------------------------------------------------------ решение по КП
const acceptDialogOpen = ref(false)
const rejectDialogOpen = ref(false)
const accepting = ref(false)
const rejecting = ref(false)
const decideError = ref('')

const deliveryMethod = ref<string>('PICKUP')
const contactName = ref('')
const phone = ref('')
const addressId = ref('')
const newAddressLine = ref('')
const newCity = ref('')
const addresses = ref<OrganizationAddress[]>([])
const addressesLoading = ref(false)

const DELIVERY_OPTIONS = [
  { value: 'PICKUP', label: 'Самовывоз', description: 'Забрать со склада продавца' },
  { value: 'DELIVERY', label: 'Доставка', description: 'По адресу из книги адресов организации' },
]

function addressLabel(address: OrganizationAddress): string {
  const parts = [address.addressLine, address.city, address.postalCode].filter(Boolean)
  return address.label ? `${address.label} — ${parts.join(', ')}` : parts.join(', ')
}

async function openAcceptDialog() {
  decideError.value = ''
  deliveryMethod.value = 'PICKUP'
  contactName.value = ''
  phone.value = ''
  addressId.value = ''
  newAddressLine.value = ''
  newCity.value = ''
  acceptDialogOpen.value = true
  if (addresses.value.length) return
  addressesLoading.value = true
  try {
    addresses.value = await listAddresses()
  } catch {
    // Сбой адресной книги не блокирует самовывоз: доставку можно указать
    // новым адресом или повторить попытку кнопкой.
  } finally {
    addressesLoading.value = false
  }
}

async function reloadAddresses() {
  addressesLoading.value = true
  try {
    addresses.value = await listAddresses()
  } finally {
    addressesLoading.value = false
  }
}

const needNewAddress = computed(() => deliveryMethod.value === 'DELIVERY' && addressId.value === 'NEW')

function validateAccept(): string {
  if (deliveryMethod.value === 'DELIVERY') {
    if (!contactName.value.trim()) return 'Укажите контактное лицо'
    if (!phone.value.trim()) return 'Укажите телефон'
    if (addressId.value === 'NEW' && !newAddressLine.value.trim()) return 'Укажите адрес доставки'
    if (addressId.value === '') return 'Выберите адрес доставки'
  }
  return ''
}

async function submitAccept() {
  if (accepting.value || !quote.value) return
  decideError.value = validateAccept()
  if (decideError.value) return

  const current = quote.value
  accepting.value = true
  try {
    let resolvedAddressId: string | undefined
    if (deliveryMethod.value === 'DELIVERY' && addressId.value === 'NEW') {
      const created = await createAddress({
        kind: 'DELIVERY',
        addressLine: newAddressLine.value.trim(),
        city: newCity.value.trim() || null,
        recipientName: contactName.value.trim() || null,
        phone: phone.value.trim() || null,
      })
      resolvedAddressId = created.id
    } else if (deliveryMethod.value === 'DELIVERY') {
      resolvedAddressId = addressId.value
    }

    const result = await repository.accept(
      current.id,
      {
        delivery: {
          method: deliveryMethod.value === 'DELIVERY' ? 'DELIVERY' : 'PICKUP',
          ...(deliveryMethod.value === 'DELIVERY'
            ? {
                contactName: contactName.value.trim(),
                phone: phone.value.trim(),
                addressId: resolvedAddressId,
              }
            : {}),
        },
      },
      newIdempotencyKey(),
    )
    acceptDialogOpen.value = false
    await navigateTo(`/orders/${encodeURIComponent(result.orderId)}`)
  } catch (cause) {
    decideError.value = problemMessage(cause, 'Не удалось принять КП')
  } finally {
    accepting.value = false
  }
}

function openRejectDialog() {
  decideError.value = ''
  rejectDialogOpen.value = true
}

async function submitReject() {
  if (rejecting.value || !quote.value) return
  rejecting.value = true
  decideError.value = ''
  try {
    quote.value = await repository.reject(quote.value.id)
    rejectDialogOpen.value = false
  } catch (cause) {
    decideError.value = problemMessage(cause, 'Не удалось отказаться от КП')
  } finally {
    rejecting.value = false
  }
}

onMounted(() => {
  isMounted = true
  void load()
})

watch(
  () => (Array.isArray(route.params.id) ? route.params.id[0] : route.params.id),
  () => {
    if (isMounted) void load()
  },
)

onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
})
</script>

<template>
  <div class="min-w-0" data-testid="quote-detail-page">
    <nav class="mb-5 flex min-h-11 items-center gap-2 text-sm text-ink-muted" aria-label="Навигация КП">
      <NuxtLink to="/quotes" class="inline-flex min-h-11 items-center hover:text-action">КП</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-3.5 text-ink-faint" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Детали</span>
    </nav>

    <div v-if="loading" class="space-y-5" data-testid="quote-detail-loading" aria-live="polite" aria-busy="true">
      <UiSkeleton class="h-24 w-full" /><UiSkeleton class="h-64 w-full" />
      <span class="sr-only">Загрузка КП</span>
    </div>

    <UiEmptyState
      v-else-if="notFound"
      title="КП не найдено"
      description="Возможно, ссылка устарела, КП ещё не отправлено или недоступно в вашем контексте."
      icon="heroicons:document-text"
      data-testid="quote-detail-not-found"
    >
      <template #action>
        <NuxtLink to="/quotes" class="inline-flex min-h-11 items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">
          К списку КП
        </NuxtLink>
      </template>
    </UiEmptyState>

    <UiErrorState
      v-else-if="error && !quote"
      title="КП недоступно"
      :description="error"
      data-testid="quote-detail-error"
      @retry="load"
    />

    <article v-else-if="quote" data-testid="quote-detail">
      <PageHeading
        eyebrow="Коммерческие предложения"
        :title="numberLabel()"
        :description="`Создано ${formatDateTime(quote.createdAt)} · обновлено ${formatDateTime(quote.updatedAt)}`"
      >
        <template #actions>
          <UiStatusBadge
            :tone="STATUS_META[quote.status].tone"
            :label="STATUS_META[quote.status].label"
            dot
            data-testid="quote-detail-status"
          />
          <UiButton
            variant="outline"
            size="touch"
            :loading="downloadActiveId === quote.id"
            :disabled="!downloadable || downloadActiveId !== null"
            :title="downloadable ? '' : 'PDF КП ещё готовится — запросите его у менеджера'"
            data-testid="quote-detail-download"
            @click="download"
          >
            <template #leading><Icon name="heroicons:document-arrow-down" class="size-4" /></template>
            Скачать PDF
          </UiButton>
          <UiButton
            v-if="canDecide"
            variant="primary"
            size="touch"
            :disabled="accepting || rejecting"
            data-testid="quote-detail-accept"
            @click="openAcceptDialog"
          >
            <template #leading><Icon name="heroicons:check" class="size-4" /></template>
            Принять
          </UiButton>
          <UiButton
            v-if="canDecide"
            variant="secondary"
            size="touch"
            :disabled="accepting || rejecting"
            data-testid="quote-detail-reject"
            @click="openRejectDialog"
          >
            <template #leading><Icon name="heroicons:no-symbol" class="size-4" /></template>
            Отказаться
          </UiButton>
        </template>
      </PageHeading>

      <UiErrorState
        v-if="decideError && !acceptDialogOpen && !rejectDialogOpen"
        class="mt-4"
        title="Действие не выполнено"
        :description="decideError"
        data-testid="quote-detail-action-error"
      />
      <UiErrorState
        v-if="downloadError"
        class="mt-4"
        title="PDF не скачан"
        :description="downloadError"
        data-testid="quote-detail-download-error"
      />

      <!-- Сводка -->
      <section class="mt-6 border-b border-border pb-6" aria-labelledby="quote-summary-title">
        <h2 id="quote-summary-title" class="mb-4 text-lg font-bold text-ink">Условия</h2>
        <dl class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div class="flex justify-between gap-4 sm:block">
            <dt class="text-ink-muted">Номер</dt>
            <dd class="numeric font-medium text-ink sm:mt-1">{{ quote.number ?? '—' }}</dd>
          </div>
          <div class="flex justify-between gap-4 sm:block">
            <dt class="text-ink-muted">Статус</dt>
            <dd class="font-medium text-ink sm:mt-1">{{ STATUS_META[quote.status].label }}</dd>
          </div>
          <div class="flex justify-between gap-4 sm:block">
            <dt class="text-ink-muted">Действительно до</dt>
            <dd class="font-medium text-ink sm:mt-1">
              {{ quote.validUntil ? formatDate(quote.validUntil) : 'срок не указан' }}
            </dd>
          </div>
          <div class="flex justify-between gap-4 sm:block">
            <dt class="text-ink-muted">Сумма</dt>
            <dd class="numeric font-medium text-ink sm:mt-1">
              {{ formatMoney(quote.total.amount, quote.total.currency) }}
            </dd>
          </div>
        </dl>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UiStatusBadge
            :tone="QUOTE_PDF_STATUS_META[quote.pdfStatus].tone"
            :label="`PDF: ${QUOTE_PDF_STATUS_META[quote.pdfStatus].label}`"
            data-testid="quote-detail-pdf-status"
          />
          <p v-if="!downloadable" class="text-xs leading-5 text-ink-muted">
            PDF ещё не сформирован. Кнопка «Скачать PDF» станет активной, когда менеджер подготовит файл.
          </p>
        </div>
        <p
          v-if="quote.validUntil && quote.status === 'SENT'"
          class="mt-3 text-xs leading-5 text-ink-muted"
        >
          Примите КП до {{ formatDate(quote.validUntil) }} — после истечения срока оно закроется автоматически.
        </p>
      </section>

      <!-- Позиции -->
      <section class="mt-6 border-b border-border pb-6" aria-labelledby="quote-items-title">
        <h2 id="quote-items-title" class="mb-4 text-lg font-bold text-ink">Позиции</h2>
        <div class="border border-border bg-surface" data-testid="quote-detail-items">
          <div class="overflow-x-auto">
            <UiTableFrame caption="Позиции КП" overflow-label="Позиции КП с горизонтальной прокруткой">
              <template #header>
                <tr class="border-b border-border bg-surface-2 text-xs font-semibold text-ink-muted">
                  <th scope="col" class="px-4 py-3">SKU</th>
                  <th scope="col" class="px-4 py-3">Наименование</th>
                  <th scope="col" class="px-4 py-3 text-right">Кол-во</th>
                  <th scope="col" class="px-4 py-3 text-right">Цена</th>
                  <th scope="col" class="px-4 py-3 text-right">Сумма</th>
                </tr>
              </template>
              <tr
                v-for="item in quote.items"
                :key="item.id"
                class="border-b border-border last:border-b-0 hover:bg-surface-2"
                :data-testid="`quote-detail-item-${item.id}`"
              >
                <td class="numeric whitespace-nowrap px-4 py-3 font-mono text-xs">{{ item.sku }}</td>
                <td class="px-4 py-3">
                  <p class="font-medium text-ink">{{ item.name }}</p>
                  <p v-if="item.comment" class="mt-0.5 text-xs text-ink-muted">{{ item.comment }}</p>
                </td>
                <td class="numeric px-4 py-3 text-right">{{ item.quantity }}</td>
                <td class="numeric whitespace-nowrap px-4 py-3 text-right">
                  {{ formatMoney(item.unitPrice.amount, item.unitPrice.currency) }}
                </td>
                <td class="numeric whitespace-nowrap px-4 py-3 text-right font-semibold">
                  {{ formatMoney(item.lineTotal.amount, item.lineTotal.currency) }}
                </td>
              </tr>
              <tr class="bg-surface-2">
                <td colspan="4" class="px-4 py-3 text-right text-sm font-semibold text-ink">Итого</td>
                <td class="numeric whitespace-nowrap px-4 py-3 text-right font-bold text-ink" data-testid="quote-detail-total">
                  {{ formatMoney(quote.total.amount, quote.total.currency) }}
                </td>
              </tr>
            </UiTableFrame>
          </div>
        </div>
      </section>
    </article>

    <!-- Принять: способ получения и доставка -->
    <UiDialog
      v-model:open="acceptDialogOpen"
      title="Принять коммерческое предложение"
      :description="quote ? `По КП ${numberLabel()} будет создана заявка на сумму ${formatMoney(quote.total.amount, quote.total.currency)}` : ''"
      :close-on-overlay="false"
      data-testid="quote-accept-dialog"
    >
      <div class="space-y-4">
        <UiRadioGroup
          v-model="deliveryMethod"
          label="Способ получения"
          name="quote-delivery-method"
          orientation="horizontal"
          :options="DELIVERY_OPTIONS"
          :disabled="accepting"
          data-testid="quote-accept-method"
        />

        <template v-if="deliveryMethod === 'DELIVERY'">
          <UiField for="quote-accept-contact" label="Контактное лицо">
            <input
              id="quote-accept-contact"
              v-model="contactName"
              type="text"
              autocomplete="name"
              class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              data-testid="quote-accept-contact"
            >
          </UiField>
          <UiField for="quote-accept-phone" label="Телефон">
            <input
              id="quote-accept-phone"
              v-model="phone"
              type="tel"
              autocomplete="tel"
              placeholder="+375 …"
              class="numeric block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              data-testid="quote-accept-phone"
            >
          </UiField>
          <UiField for="quote-accept-address" label="Адрес доставки">
            <select
              id="quote-accept-address"
              v-model="addressId"
              class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              data-testid="quote-accept-address"
            >
              <option value="" :disabled="addresses.length > 0">Выберите адрес…</option>
              <option v-if="addressesLoading" value="" disabled>Загружаем адресную книгу…</option>
              <option v-for="address in addresses" :key="address.id" :value="address.id">
                {{ addressLabel(address) }}
              </option>
              <option value="NEW">Новый адрес…</option>
            </select>
            <button
              type="button"
              class="mt-1 inline-flex min-h-8 items-center gap-1 text-xs font-semibold text-ink-muted hover:text-ink"
              :disabled="addressesLoading"
              @click="reloadAddresses"
            >
              <Icon name="heroicons:arrow-path" class="size-3.5" aria-hidden="true" />Обновить список
            </button>
          </UiField>
          <div v-if="needNewAddress" class="grid gap-3 sm:grid-cols-2" data-testid="quote-accept-new-address">
            <UiField for="quote-accept-address-line" label="Адрес">
              <input
                id="quote-accept-address-line"
                v-model="newAddressLine"
                type="text"
                placeholder="Улица, дом, офис"
                class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              >
            </UiField>
            <UiField for="quote-accept-address-city" label="Город">
              <input
                id="quote-accept-address-city"
                v-model="newCity"
                type="text"
                placeholder="необязательно"
                class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              >
            </UiField>
          </div>
          <p class="text-xs leading-5 text-ink-muted">
            Новый адрес сохранится в адресной книге организации и будет доступен при следующих заявках.
          </p>
        </template>

        <p
          v-if="decideError"
          class="badge-danger"
          role="alert"
          data-testid="quote-accept-error"
        >
          {{ decideError }}
        </p>
      </div>

      <template #footer>
        <UiButton variant="secondary" size="touch" :disabled="accepting" @click="acceptDialogOpen = false">
          Отмена
        </UiButton>
        <UiButton size="touch" :loading="accepting" :disabled="accepting" data-testid="quote-accept-submit" @click="submitAccept">
          Принять и создать заявку
        </UiButton>
      </template>
    </UiDialog>

    <!-- Отказаться: подтверждение -->
    <UiDialog
      v-model:open="rejectDialogOpen"
      title="Отказаться от КП?"
      :description="quote ? `КП ${numberLabel()} перейдёт в статус «Отклонено». Решение нельзя отменить.` : ''"
      data-testid="quote-reject-dialog"
    >
      <p
        v-if="decideError"
        class="badge-danger"
        role="alert"
        data-testid="quote-reject-error"
      >
        {{ decideError }}
      </p>
      <template #footer>
        <UiButton variant="secondary" size="touch" :disabled="rejecting" @click="rejectDialogOpen = false">
          Вернуться
        </UiButton>
        <UiButton variant="danger" size="touch" :loading="rejecting" :disabled="rejecting" data-testid="quote-reject-submit" @click="submitReject">
          Отказаться
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>
