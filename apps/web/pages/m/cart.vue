<script setup lang="ts">
// Мобильная корзина (Mini App): позиции → оформление заявки → «Заявка отправлена».
import type { CartItemRead, OrderCreate, OrderRead } from '~/types/api'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
useHead({ title: 'Корзина' })
const { request } = useApi()
const { thumbOf } = useProductPhoto()
const { data: cart, loading, refresh, update, remove } = useCart()

const stage = ref<'cart' | 'checkout' | 'done'>('cart')
const notes = ref('')
const submitting = ref(false)
const error = ref('')
const updatingSku = ref<string | null>(null)
const removingSku = ref<string | null>(null)
const createdOrder = ref<OrderRead | null>(null)

const currency = computed(() => cart.value?.items[0]?.currency || 'BYN')

function shortId(id: string) {
  return id.slice(0, 8)
}

async function changeQty(item: CartItemRead, delta: number) {
  const qty = item.quantity + delta
  if (qty < 1) return
  updatingSku.value = item.sku
  error.value = ''
  try {
    await update(item.sku, { quantity: qty })
  } catch (e) {
    // 422 по остаткам: показываем детали бэка, а не общий текст.
    error.value = getErrorStatus(e) === 422
      ? getDetailedErrorMessage(e, 'Не удалось изменить количество')
      : getErrorMessage(e, 'Не удалось изменить количество')
  } finally {
    updatingSku.value = null
  }
}

async function removeItem(item: CartItemRead) {
  removingSku.value = item.sku
  error.value = ''
  try {
    await remove(item.sku)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось удалить позицию')
  } finally {
    removingSku.value = null
  }
}

function goCheckout() {
  error.value = ''
  stage.value = 'checkout'
}

function backToCart() {
  error.value = ''
  stage.value = 'cart'
}

async function submitOrder() {
  if (submitting.value || !cart.value) return
  submitting.value = true
  error.value = ''
  const payload: OrderCreate = {
    items: cart.value.items.map(i => ({ sku: i.sku, quantity: i.quantity, note: i.note })),
    notes: notes.value || null,
    price_calc_mode: 'fixed',
  }
  try {
    createdOrder.value = await request<OrderRead>('/api/v1/orders', { method: 'POST', body: payload })
    // Корзина очищается на бэке атомарно при создании заявки — сбрасываем локальный стейт.
    await refresh()
    stage.value = 'done'
  } catch (e) {
    error.value = getErrorStatus(e) === 422
      ? getDetailedErrorMessage(e, 'Не удалось оформить заявку')
      : getErrorMessage(e, 'Не удалось оформить заявку')
  } finally {
    submitting.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div>
    <template v-if="stage === 'cart'">
      <PageHeading
        eyebrow="Заявка"
        title="Корзина"
        :description="`Позиций: ${cart?.total_items || 0}`"
      />
      <div v-if="error" class="mb-4 border border-danger/50 bg-danger-soft p-3 text-sm text-ink" role="alert">{{ error }}</div>

      <div v-if="loading && !cart" class="border border-border bg-surface" aria-label="Загрузка корзины" aria-busy="true">
        <div v-for="i in 3" :key="i" class="h-28 border-b border-border p-3 last:border-b-0"><div class="skeleton h-full w-full" /></div>
      </div>
      <div v-else-if="!cart || !cart.total_items" class="border border-border bg-surface p-5">
        <p class="text-sm font-semibold text-ink">Корзина пуста</p>
        <p class="mt-1 text-sm text-ink-muted">Добавьте товары из каталога.</p>
        <NuxtLink to="/m/catalog" class="btn-primary mt-4 inline-flex min-h-11 items-center">Перейти в каталог</NuxtLink>
      </div>
      <template v-else>
        <section class="border border-border bg-surface" aria-label="Позиции корзины">
          <article v-for="item in cart.items" :key="item.product_id" class="grid grid-cols-[56px_minmax(0,1fr)] gap-3 border-b border-border p-3 last:border-b-0 sm:grid-cols-[64px_minmax(0,1fr)_auto]">
            <div class="flex size-14 items-center justify-center overflow-hidden border border-border bg-background sm:size-16">
              <img v-if="thumbOf(item.photo_key)" :src="thumbOf(item.photo_key)!" :alt="item.name" loading="lazy" class="size-full object-contain">
              <Icon v-else name="heroicons:photo" class="size-6 text-ink-faint" />
            </div>
            <div class="min-w-0">
              <NuxtLink :to="`/m/catalog/${encodeURIComponent(item.sku)}`" class="line-clamp-2 text-sm font-semibold leading-5 text-ink hover:text-action">{{ item.name }}</NuxtLink>
              <p class="numeric mt-1 truncate text-xs text-ink-muted">{{ item.sku }}<span v-if="item.brand_name"> · {{ item.brand_name }}</span></p>
              <div class="mt-3 flex items-center justify-between gap-2">
                <div class="flex items-center">
                  <button type="button" class="btn-outline size-11" :disabled="updatingSku === item.sku" :aria-label="`Уменьшить количество ${item.name}`" @click="changeQty(item, -1)"><Icon name="heroicons:minus" class="size-4" /></button>
                  <span class="numeric w-10 text-center text-sm font-bold">{{ item.quantity }}</span>
                  <button type="button" class="btn-outline size-11" :disabled="updatingSku === item.sku" :aria-label="`Увеличить количество ${item.name}`" @click="changeQty(item, 1)"><Icon name="heroicons:plus" class="size-4" /></button>
                </div>
                <button type="button" class="btn-ghost size-11 text-danger" :disabled="removingSku === item.sku" :aria-label="`Удалить ${item.name}`" @click="removeItem(item)"><Icon name="heroicons:trash" class="size-5" /></button>
              </div>
            </div>
            <div class="col-start-2 flex items-end border-t border-border pt-2 sm:col-start-auto sm:flex-col sm:items-end sm:border-t-0 sm:pt-0">
              <span class="numeric text-xs text-ink-muted">{{ formatMoney(item.unit_price, item.currency) }} / шт</span>
              <span class="numeric text-sm font-bold text-ink">{{ formatMoney(item.line_total, item.currency) }}</span>
            </div>
          </article>
        </section>
        <section class="mt-3 border border-border bg-surface p-4" aria-label="Итог корзины">
          <div class="flex items-baseline justify-between"><span class="text-sm text-ink-muted">Итого · {{ cart.total_items }} поз.</span><span class="numeric text-lg font-bold">{{ formatMoney(cart.total_amount, currency) }}</span></div>
          <button type="button" class="btn-primary mt-4 min-h-11 w-full justify-center" @click="goCheckout"><Icon name="heroicons:document-check" class="size-4" /> Оформить заявку</button>
        </section>
      </template>
    </template>

    <template v-else-if="stage === 'checkout'">
      <PageHeading eyebrow="Шаг 2 из 2" title="Проверьте заявку" />
      <div v-if="error" class="mb-4 border border-danger/50 bg-danger-soft p-3 text-sm text-ink" role="alert">{{ error }}</div>
      <section class="border border-border bg-surface p-4">
        <div class="flex items-baseline justify-between border-b border-border pb-3"><span class="text-sm text-ink-muted">{{ cart?.total_items ?? 0 }} позиций</span><span class="numeric text-lg font-bold">{{ formatMoney(cart?.total_amount ?? 0, currency) }}</span></div>
        <p v-if="currency !== 'BYN'" class="mt-3 border border-info/50 bg-info-soft p-3 text-sm">Курс {{ currency }} будет зафиксирован при отправке.</p>
      </section>
      <section class="mt-3 border border-border bg-surface p-4">
        <label class="label" for="m_notes">Комментарий (необязательно)</label>
        <textarea id="m_notes" v-model="notes" rows="3" class="input mt-1 resize-y" placeholder="Сертификат, сроки доставки…" />
        <button type="button" class="btn-primary mt-4 min-h-11 w-full justify-center" :disabled="submitting" @click="submitOrder">
          <span v-if="submitting" class="size-4 animate-spin border-2 border-white/40 border-t-white" />
          {{ submitting ? 'Отправка…' : 'Отправить заявку' }}
        </button>
        <button type="button" class="btn-ghost mt-2 min-h-11 w-full justify-center" @click="backToCart">Назад в корзину</button>
      </section>
    </template>

    <section v-else class="border border-border bg-surface p-5">
      <PageHeading
        eyebrow="Заявка принята"
        title="Заявка отправлена"
        :description="createdOrder ? `№${shortId(createdOrder.id)} · ${formatMoney(createdOrder.total_amount, createdOrder.currency_code)}` : undefined"
      />
      <NuxtLink to="/m/orders" class="btn-primary mt-5 inline-flex min-h-11 w-full items-center justify-center">Мои заявки</NuxtLink>
      <NuxtLink to="/m/catalog" class="btn-ghost mt-2 inline-flex min-h-11 w-full items-center justify-center">В каталог</NuxtLink>
    </section>
  </div>
</template>
