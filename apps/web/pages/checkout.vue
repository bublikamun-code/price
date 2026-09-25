<script setup lang="ts">
import type { OrderCreate, OrderDeliveryCreate } from '~/domain/api/v2/order.schema'
import { toAppProblem, AppProblem } from '~/domain/api/v2/problem'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Оформление заявки' })

const cartV2 = useCartV2()
const ordersV2 = useOrdersV2()
const cart = computed(() => cartV2.store.cart)
const loading = computed(() => cartV2.store.loading || ordersV2.store.loading)
const submitting = ref(false)
const loadError = ref<AppProblem | null>(null)
const submitError = ref<AppProblem | null>(null)

const deliveryMethod = ref<OrderDeliveryCreate['method']>('PICKUP')
const deliveryContact = ref('')
const deliveryPhone = ref('')
const deliveryDate = ref('')
const deliveryComment = ref('')
const contactError = ref('')
const phoneError = ref('')

function problem(cause: unknown, fallback: string): AppProblem {
  return cause instanceof AppProblem ? cause : toAppProblem(cause, fallback)
}

function problemMessage(cause: AppProblem): string {
  if (!cause.fieldErrors.length) return cause.message
  const details = cause.fieldErrors
    .map((field) => `${field.field}: ${field.message}`)
    .join('; ')
  return `${cause.message}: ${details}`
}

async function loadCart() {
  loadError.value = null
  try {
    const snapshot = await cartV2.ensureLoaded()
    if (!snapshot) {
      throw new AppProblem({
        code: 'CHECKOUT_SESSION_UNAVAILABLE',
        message: 'Не удалось определить коммерческий контекст заявки',
        isProblemDetails: false,
        retryable: false,
      })
    }
  } catch (cause) {
    loadError.value = problem(cause, 'Не удалось загрузить состав заявки')
  }
}

function validateDelivery() {
  contactError.value = ''
  phoneError.value = ''
  if (deliveryMethod.value === 'DELIVERY') {
    if (!deliveryContact.value.trim()) contactError.value = 'Укажите контактное лицо'
    if (!deliveryPhone.value.trim()) phoneError.value = 'Укажите телефон для доставки'
  }
  return !contactError.value && !phoneError.value
}

function buildPayload(): OrderCreate {
  const delivery: OrderDeliveryCreate = deliveryMethod.value === 'PICKUP'
    ? {
        method: 'PICKUP',
        comment: deliveryComment.value.trim() || null,
      }
    : {
        method: 'DELIVERY',
        contactName: deliveryContact.value.trim() || null,
        phone: deliveryPhone.value.trim() || null,
        preferredDate: deliveryDate.value || null,
        comment: deliveryComment.value.trim() || null,
      }

  return {
    // v2 order lines are keyed by productId; SKU is a display field only.
    items: (cart.value?.items ?? []).map((item) => ({
      productId: item.productId,
      quantity: String(item.quantity),
      note: item.note,
    })),
    delivery,
  }
}

async function submit() {
  if (!cart.value?.items.length || submitting.value || ordersV2.store.loading) return
  submitError.value = null
  if (!validateDelivery()) return

  submitting.value = true
  try {
    // The orders store owns the v2 Idempotency-Key and serializes retries.
    const result = await ordersV2.submit(buildPayload())
    await navigateTo(`/orders/${result.order.id}`)
  } catch (cause) {
    submitError.value = problem(cause, 'Не удалось оформить заявку')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void loadCart()
})
</script>

<template>
  <div class="min-w-0" data-testid="checkout-page">
    <nav class="mb-5 flex min-h-11 items-center gap-2 text-sm text-ink-muted" aria-label="Навигация оформления">
      <NuxtLink to="/cart" class="inline-flex min-h-11 items-center hover:text-action">Заявка</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-3.5 text-ink-faint" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Оформление</span>
    </nav>

    <PageHeading
      eyebrow="Новая заявка"
      title="Оформление"
      description="Последовательно проверьте состав, способ получения и подтвердите отправку."
    />

    <UiErrorState v-if="loadError && !cart" class="mb-6" title="Заявка недоступна" :description="problemMessage(loadError)" :code="loadError.code" data-testid="checkout-error" @retry="loadCart" />

    <div v-else-if="loading && !cart" class="space-y-4 border-y border-border py-4" aria-busy="true">
      <UiSkeleton class="h-16 w-full" /><UiSkeleton class="h-16 w-full" /><UiSkeleton class="h-48 w-full" />
      <span class="sr-only">Загрузка состава заявки</span>
    </div>

    <UiEmptyState v-else-if="!cart || !cart.items.length" title="Заявка пока пуста" description="Добавьте товары, чтобы оформить заявку." icon="heroicons:clipboard-document-list">
      <template #action><NuxtLink to="/catalog" class="inline-flex min-h-11 items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">В каталог</NuxtLink></template>
    </UiEmptyState>

    <form v-else id="checkout-form" class="grid items-start gap-6 pb-24 lg:grid-cols-[minmax(0,1fr)_20rem] lg:pb-0" novalidate @submit.prevent="submit">
      <div class="min-w-0 space-y-8">
        <section aria-labelledby="checkout-composition-title">
          <div class="flex items-start gap-3 border-b border-border pb-3">
            <span class="numeric flex size-8 shrink-0 items-center justify-center bg-action text-sm font-bold text-action-on">01</span>
            <div>
              <h2 id="checkout-composition-title" class="text-lg font-bold text-ink">Состав заявки</h2>
              <p class="mt-1 text-sm text-ink-muted">Позиции зафиксированы из текущей заявки.</p>
            </div>
          </div>
          <div class="mt-4 flex items-center justify-between gap-4 border-b border-border pb-3 text-xs">
            <span class="font-semibold text-ink">Товары</span>
            <span class="numeric text-ink-muted">{{ cart.totalItems }} шт.</span>
          </div>
          <div class="border-b border-border" data-testid="checkout-line-records">
            <OrderLineRecord v-for="item in cart.items" :key="item.productId" :line="item" readonly />
          </div>
          <div class="mt-3 flex justify-end"><NuxtLink to="/cart" class="inline-flex min-h-11 items-center px-3 text-sm font-semibold text-ink hover:bg-surface-2" :aria-disabled="submitting" :tabindex="submitting ? -1 : undefined" @click="submitting && $event.preventDefault()">Изменить состав</NuxtLink></div>
        </section>

        <section aria-labelledby="checkout-delivery-title">
          <div class="flex items-start gap-3 border-b border-border pb-3">
            <span class="numeric flex size-8 shrink-0 items-center justify-center bg-action text-sm font-bold text-action-on">02</span>
            <div>
              <h2 id="checkout-delivery-title" class="text-lg font-bold text-ink">Получение</h2>
              <p class="mt-1 text-sm text-ink-muted">Выберите способ и укажите доступные данные.</p>
            </div>
          </div>

          <fieldset class="mt-4" :disabled="submitting">
            <legend class="sr-only">Способ получения</legend>
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="flex min-h-16 cursor-pointer items-start gap-3 border p-4 transition-colors" :class="deliveryMethod === 'PICKUP' ? 'border-action bg-action-soft' : 'border-border bg-surface hover:border-border-strong'">
                <input v-model="deliveryMethod" type="radio" value="PICKUP" name="delivery-method" class="mt-1 size-4 shrink-0 accent-action">
                <span><span class="block text-sm font-semibold text-ink">Самовывоз</span><span class="mt-1 block text-xs leading-5 text-ink-muted">Пункт выдачи и детали уточнит менеджер.</span></span>
              </label>
              <label class="flex min-h-16 cursor-pointer items-start gap-3 border p-4 transition-colors" :class="deliveryMethod === 'DELIVERY' ? 'border-action bg-action-soft' : 'border-border bg-surface hover:border-border-strong'">
                <input v-model="deliveryMethod" type="radio" value="DELIVERY" name="delivery-method" class="mt-1 size-4 shrink-0 accent-action">
                <span><span class="block text-sm font-semibold text-ink">Доставка</span><span class="mt-1 block text-xs leading-5 text-ink-muted">Контакт, телефон и адрес для передачи.</span></span>
              </label>
            </div>

            <div v-if="deliveryMethod === 'DELIVERY'" class="mt-5 grid gap-4 sm:grid-cols-2">
              <UiField for="delivery-contact" label="Контактное лицо" required :error="contactError">
                <UiInput id="delivery-contact" v-model="deliveryContact" :error="contactError" :disabled="submitting" placeholder="Иван Иванов" required />
              </UiField>
              <UiField for="delivery-phone" label="Телефон" required :error="phoneError">
                <UiInput id="delivery-phone" v-model="deliveryPhone" type="tel" :error="phoneError" :disabled="submitting" placeholder="+375 29 000-00-00" required />
              </UiField>
              <UiField for="delivery-date" label="Желаемая дата" description="Необязательно">
                <UiInput id="delivery-date" v-model="deliveryDate" type="date" :disabled="submitting" />
              </UiField>
            </div>
          </fieldset>

          <UiField for="delivery-comment" class="mt-5" :label="deliveryMethod === 'DELIVERY' ? 'Адрес и комментарий' : 'Комментарий к получению'" description="До 2000 символов">
            <UiTextarea id="delivery-comment" v-model="deliveryComment" :disabled="submitting" placeholder="Адрес, удобное время приёмки или дополнительные пожелания" />
          </UiField>
        </section>

        <section aria-labelledby="checkout-confirmation-title">
          <div class="flex items-start gap-3 border-b border-border pb-3">
            <span class="numeric flex size-8 shrink-0 items-center justify-center bg-action text-sm font-bold text-action-on">03</span>
            <div>
              <h2 id="checkout-confirmation-title" class="text-lg font-bold text-ink">Подтверждение</h2>
              <p class="mt-1 text-sm text-ink-muted">После отправки заявка появится в истории заказов.</p>
            </div>
          </div>
          <ul class="mt-4 border-y border-border bg-surface px-4 py-2 text-sm text-ink-muted" aria-label="Условия подтверждения">
            <li class="flex min-h-11 items-center gap-3 border-b border-border last:border-b-0"><Icon name="heroicons:check-circle" class="size-4 shrink-0 text-success-text" aria-hidden="true" />Состав выбран из текущей заявки</li>
            <li class="flex min-h-11 items-center gap-3 border-b border-border last:border-b-0"><Icon name="heroicons:check-circle" class="size-4 shrink-0 text-success-text" aria-hidden="true" />Данные передаются в действующий коммерческий контекст</li>
            <li class="flex min-h-11 items-center gap-3"><Icon name="heroicons:shield-check" class="size-4 shrink-0 text-success-text" aria-hidden="true" />Повторная отправка защищена идемпотентностью</li>
          </ul>
        </section>
      </div>

      <aside class="bg-service p-5 text-service-ink lg:sticky lg:top-24" aria-labelledby="checkout-summary-title" data-testid="checkout-summary">
        <div class="flex items-start justify-between gap-4 border-b border-service-border pb-4">
          <div><p class="text-xs font-semibold uppercase tracking-wider text-service-muted">Проверка</p><h2 id="checkout-summary-title" class="mt-1 text-lg font-bold">Параметры заявки</h2></div>
          <Icon name="heroicons:document-check" class="size-5 text-service-muted" aria-hidden="true" />
        </div>
        <dl class="space-y-3 border-b border-service-border py-4 text-sm">
          <div class="flex justify-between gap-4"><dt class="text-service-muted">Позиций</dt><dd class="numeric font-semibold">{{ cart.totalItems }}</dd></div>
          <div class="flex justify-between gap-4"><dt class="text-service-muted">Получение</dt><dd class="font-semibold">{{ deliveryMethod === 'PICKUP' ? 'Самовывоз' : 'Доставка' }}</dd></div>
          <div class="flex items-baseline justify-between gap-4 pt-2"><dt class="font-semibold">Итого</dt><dd class="numeric text-xl font-bold" data-testid="checkout-grand-total">{{ formatMoney(cart.total.amount, cart.total.currency) }}</dd></div>
        </dl>
        <p v-if="cart.total.currency !== 'BYN'" class="mt-4 border border-service-border p-3 text-xs leading-5 text-service-muted">Курс {{ cart.total.currency }} фиксируется при создании заявки.</p>
        <p class="mt-4 text-xs leading-5 text-service-muted">Итоговая цена и наличие подтверждаются сервером.</p>
        <UiErrorState v-if="submitError" class="mt-4 bg-surface text-ink" title="Заявка не создана" :description="problemMessage(submitError)" :code="submitError.code" />
        <UiButton class="mt-5 hidden w-full lg:inline-flex" size="touch" type="submit" :loading="submitting" :disabled="loading || !cart.items.length" data-testid="checkout-submit">
          <template #leading><Icon name="heroicons:paper-airplane" class="size-4" aria-hidden="true" /></template>{{ submitting ? 'Отправка…' : 'Отправить заявку' }}
        </UiButton>
        <UiButton class="mt-2 w-full !border-service-border !text-service-ink hover:!bg-service-2" size="touch" :disabled="submitting" @click="navigateTo('/cart')">Назад к заявке</UiButton>
        <p class="mt-4 text-xs leading-5 text-service-muted">Ключ идемпотентности формируется и повторно используется composable заказов.</p>
      </aside>
    </form>

    <StickyActionBar
      v-if="cart?.items.length"
      :total="formatMoney(cart.total.amount, cart.total.currency)"
      label="Отправить заявку"
      form="checkout-form"
      :busy="submitting"
      :disabled="loading || !cart.items.length"
      data-testid="checkout-submit-mobile"
    />
  </div>
</template>
