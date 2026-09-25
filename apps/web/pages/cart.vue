<script setup lang="ts">
import type { CartLine } from '~/domain/api/v2/cart.schema'
import { toAppProblem, AppProblem } from '~/domain/api/v2/problem'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Заявка' })

const { store, ensureLoaded, replaceItem, removeItem: removeCartItem, clear } = useCartV2()
const cart = computed(() => store.cart)
const loadError = ref<AppProblem | null>(null)
const actionError = ref<AppProblem | null>(null)
const updatingProductId = ref<string | null>(null)
const removingProductId = ref<string | null>(null)
const clearing = ref(false)

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
    const snapshot = await ensureLoaded()
    if (!snapshot) {
      throw new AppProblem({
        code: 'CART_SESSION_UNAVAILABLE',
        message: 'Не удалось определить коммерческий контекст заявки',
        isProblemDetails: false,
        retryable: false,
      })
    }
  } catch (cause) {
    loadError.value = problem(cause, 'Не удалось загрузить состав заявки')
  }
}

async function changeQty(item: CartLine, delta: number) {
  const quantity = item.quantity + delta
  if (quantity < 1 || updatingProductId.value || store.saving) return
  updatingProductId.value = item.productId
  actionError.value = null
  try {
    await replaceItem(item.productId, { quantity: String(quantity), note: item.note })
  } catch (cause) {
    actionError.value = problem(cause, 'Не удалось изменить количество')
  } finally {
    updatingProductId.value = null
  }
}

async function removeItem(item: CartLine) {
  if (removingProductId.value || store.saving) return
  removingProductId.value = item.productId
  actionError.value = null
  try {
    await removeCartItem(item.productId)
  } catch (cause) {
    actionError.value = problem(cause, 'Не удалось удалить позицию')
  } finally {
    removingProductId.value = null
  }
}

async function clearAll() {
  if (clearing.value || !cart.value?.totalItems) return
  if (!window.confirm('Очистить заявку?')) return
  clearing.value = true
  actionError.value = null
  try {
    await clear()
  } catch (cause) {
    actionError.value = problem(cause, 'Не удалось очистить заявку')
  } finally {
    clearing.value = false
  }
}

function retryLoad() {
  void loadCart()
}

onMounted(() => {
  void loadCart()
})
</script>

<template>
  <div class="min-w-0" data-testid="cart-page">
    <PageHeading
      eyebrow="Текущая заявка"
      title="Заявка"
      description="Проверьте состав и количество перед оформлением."
    >
      <template #actions>
        <UiButton v-if="cart?.totalItems" variant="danger" size="touch" :loading="clearing" :disabled="store.saving" @click="clearAll">
          <template #leading><Icon name="heroicons:trash" class="size-4" aria-hidden="true" /></template>
          Очистить
        </UiButton>
      </template>
    </PageHeading>

    <UiErrorState v-if="loadError && !cart" class="mb-6" title="Заявка недоступна" :description="problemMessage(loadError)" :code="loadError.code" data-testid="cart-error" @retry="retryLoad" />

    <div v-else-if="store.loading && !cart" class="space-y-3 border-y border-border py-3" aria-label="Загрузка состава заявки" aria-busy="true">
      <UiSkeleton v-for="index in 3" :key="index" class="h-16 w-full" />
    </div>

    <UiEmptyState v-else-if="!cart || !cart.totalItems" title="Заявка пока пуста" description="Добавьте товары из каталога, чтобы оформить заявку." icon="heroicons:clipboard-document-list" data-testid="cart-empty">
      <template #action>
        <NuxtLink to="/catalog" class="inline-flex min-h-11 items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">Перейти в каталог</NuxtLink>
      </template>
    </UiEmptyState>

    <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <UiPanel class="min-w-0 p-4 sm:p-5">
        <ol class="grid grid-cols-3 border-y border-border bg-surface" aria-label="Этапы оформления">
          <li class="flex min-h-12 items-center justify-center gap-2 border-r border-border px-2 text-xs font-semibold text-action sm:text-sm">
            <span class="flex size-6 shrink-0 items-center justify-center bg-action text-action-on">1</span><span>Товары</span>
          </li>
          <li class="flex min-h-12 items-center justify-center gap-2 border-r border-border px-2 text-xs font-semibold text-ink-muted sm:text-sm">
            <span class="flex size-6 shrink-0 items-center justify-center border border-border">2</span><span>Данные</span>
          </li>
          <li class="flex min-h-12 items-center justify-center gap-2 px-2 text-xs font-semibold text-ink-muted sm:text-sm">
            <span class="flex size-6 shrink-0 items-center justify-center border border-border">3</span><span>Подтверждение</span>
          </li>
        </ol>

        <div class="mt-5 flex items-center justify-between gap-4 border-b border-border pb-3">
          <h2 class="text-sm font-semibold text-ink">Состав заявки</h2>
          <span class="numeric text-xs text-ink-muted">{{ cart.totalItems }} {{ pluralize(cart.totalItems, 'позиция', 'позиции', 'позиций') }}</span>
        </div>

        <UiErrorState v-if="actionError" class="my-4" title="Изменение не сохранено" :description="problemMessage(actionError)" :code="actionError.code" @retry="retryLoad" />

        <div class="border-b border-border" data-testid="cart-line-records">
          <OrderLineRecord
            v-for="item in cart.items"
            :key="item.productId"
            :line="item"
            :busy="updatingProductId === item.productId || removingProductId === item.productId"
            @change="changeQty(item, $event)"
            @remove="removeItem(item)"
          />
        </div>

        <p v-if="store.conflict" class="mt-2 text-xs font-medium text-warning-text" role="status">Состав заявки изменился в другой вкладке. Показаны актуальные позиции.</p>
        <div class="mt-5 flex items-center justify-between gap-4 border-y border-border py-3 text-xs">
          <span class="text-ink-muted">Изменения сохраняются на сервере автоматически</span>
          <span class="inline-flex items-center gap-1.5 font-semibold text-success-text"><Icon name="heroicons:cloud-check" class="size-4" aria-hidden="true" />Синхронизировано</span>
        </div>
      </UiPanel>

      <aside class="rounded-surface border border-service bg-service p-5 text-service-ink lg:sticky lg:top-24" aria-labelledby="cart-summary-title" data-testid="cart-summary">
        <div class="flex items-start justify-between gap-4 border-b border-service-border pb-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-service-muted">Итого</p>
            <h2 id="cart-summary-title" class="mt-1 text-lg font-bold">Состав заявки</h2>
          </div>
          <Icon name="heroicons:document-text" class="size-5 text-service-muted" aria-hidden="true" />
        </div>
        <dl class="space-y-3 border-b border-service-border py-4 text-sm">
          <div class="flex justify-between gap-4"><dt class="text-service-muted">Позиций</dt><dd class="numeric font-semibold">{{ cart.totalItems }}</dd></div>
          <div class="flex items-baseline justify-between gap-4 pt-2">
            <dt class="font-semibold">Сумма</dt>
            <dd class="numeric text-xl font-bold" data-testid="cart-grand-total">{{ formatMoney(cart.total.amount, cart.total.currency) }}</dd>
          </div>
        </dl>
        <p class="mt-4 text-xs leading-5 text-service-muted">Итоговая цена и доступность подтверждаются при оформлении.</p>
        <NuxtLink to="/checkout" class="mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover" data-testid="cart-checkout">
          Оформить заявку
          <Icon name="heroicons:arrow-right" class="size-4" aria-hidden="true" />
        </NuxtLink>
        <NuxtLink to="/catalog" class="mt-2 inline-flex min-h-11 w-full items-center justify-center border border-service-border px-4 text-sm font-semibold text-service-ink hover:bg-service-2">Продолжить выбор</NuxtLink>
        <p class="mt-4 text-xs leading-5 text-service-muted">Оформление доступно только для действующего коммерческого клиента.</p>
      </aside>
    </div>

    <StickyActionBar v-if="cart?.totalItems" class="lg:hidden" :total="formatMoney(cart.total.amount, cart.total.currency)" label="Оформить заявку" to="/checkout" />
  </div>
</template>
