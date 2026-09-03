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
    <!-- Список позиций -->
    <template v-if="stage === 'cart'">
      <h1 class="text-lg font-bold mb-3">Корзина</h1>
      <div v-if="error" class="badge-danger w-full justify-center py-2.5 mb-3">{{ error }}</div>

      <!-- Skeleton -->
      <div v-if="loading && !cart" class="space-y-3">
        <div v-for="i in 3" :key="i" class="card p-3">
          <div class="skeleton h-16 w-full" />
        </div>
      </div>

      <!-- Пусто -->
      <div v-else-if="!cart || !cart.total_items" class="card p-8 text-center">
        <Icon name="heroicons:shopping-cart" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
        <p class="text-sm text-ink-muted mb-4">Корзина пуста</p>
        <NuxtLink to="/m/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
      </div>

      <!-- Содержимое -->
      <template v-else>
        <div class="space-y-3">
          <article v-for="item in cart.items" :key="item.product_id" class="card p-3 flex gap-3">
            <div class="w-16 h-16 shrink-0 rounded-card bg-canvas overflow-hidden flex items-center justify-center">
              <img v-if="thumbOf(item.photo_key)" :src="thumbOf(item.photo_key)!" :alt="item.name" class="w-full h-full object-contain">
              <Icon v-else name="heroicons:photo" class="w-6 h-6 text-ink-faint" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-start justify-between gap-2">
                <NuxtLink :to="`/m/catalog/${encodeURIComponent(item.sku)}`" class="text-sm font-medium leading-snug line-clamp-2">{{ item.name }}</NuxtLink>
                <button class="btn-ghost p-1.5 -m-1 text-ink-faint hover:text-danger shrink-0" :disabled="removingSku === item.sku" title="Удалить" @click="removeItem(item)">
                  <span v-if="removingSku === item.sku" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin" />
                  <Icon v-else name="heroicons:trash" class="w-4 h-4" />
                </button>
              </div>
              <p class="text-xs text-ink-faint mt-0.5">{{ item.sku }}<span v-if="item.brand_name"> · {{ item.brand_name }}</span></p>
              <div class="flex items-center justify-between gap-2 mt-2">
                <div class="flex items-center gap-1">
                  <button class="btn-outline px-2.5 py-1" :disabled="updatingSku === item.sku" @click="changeQty(item, -1)">
                    <Icon name="heroicons:minus" class="w-3.5 h-3.5" />
                  </button>
                  <span class="w-8 text-center text-sm font-medium">{{ item.quantity }}</span>
                  <button class="btn-outline px-2.5 py-1" :disabled="updatingSku === item.sku" @click="changeQty(item, 1)">
                    <Icon name="heroicons:plus" class="w-3.5 h-3.5" />
                  </button>
                </div>
                <div class="text-right">
                  <p class="text-xs text-ink-muted">{{ formatMoney(item.unit_price, item.currency) }}/шт</p>
                  <p class="text-sm font-bold">{{ formatMoney(item.line_total, item.currency) }}</p>
                </div>
              </div>
            </div>
          </article>
        </div>

        <div class="card p-4 mt-4">
          <div class="flex justify-between items-baseline">
            <span class="text-ink-muted text-sm">Итого · {{ cart.total_items }} поз.</span>
            <span class="text-lg font-bold">{{ formatMoney(cart.total_amount, currency) }}</span>
          </div>
          <button class="btn-primary w-full justify-center py-3 mt-3" @click="goCheckout">
            <Icon name="heroicons:document-check" class="w-4 h-4" /> Оформить заявку
          </button>
        </div>
      </template>
    </template>

    <!-- Оформление -->
    <template v-else-if="stage === 'checkout'">
      <h1 class="text-lg font-bold mb-3">Оформление заявки</h1>
      <div v-if="error" class="badge-danger w-full justify-center py-2.5 mb-3">{{ error }}</div>

      <div class="card p-4 mb-3">
        <p class="text-sm text-ink-muted mb-1">{{ cart?.total_items ?? 0 }} позиций будет отправлено менеджеру</p>
        <div class="flex justify-between items-baseline mt-2">
          <span class="font-medium">Итого</span>
          <span class="text-lg font-bold">{{ formatMoney(cart?.total_amount ?? 0, currency) }}</span>
        </div>
        <div v-if="currency !== 'BYN'" class="badge-info w-full justify-center py-2 mt-3"> Курс {{ currency }} будет зафиксирован при отправке </div>
      </div>

      <div class="card p-4">
        <label class="label" for="m_notes">Комментарий (необязательно)</label>
        <textarea id="m_notes" v-model="notes" rows="3" class="input py-2.5 resize-y" placeholder="Сертификат, сроки доставки…" />
        <button class="btn-primary w-full justify-center py-3 mt-4" :disabled="submitting" @click="submitOrder">
          <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <Icon v-else name="heroicons:paper-airplane" class="w-4 h-4" />
          {{ submitting ? 'Отправка…' : 'Отправить заявку' }}
        </button>
        <button class="btn-ghost w-full justify-center py-2.5 mt-2" @click="backToCart"> Назад в корзину </button>
      </div>
    </template>

    <!-- Готово -->
    <div v-else class="flex flex-col items-center justify-center text-center min-h-[60vh]">
      <span class="inline-flex items-center justify-center w-16 h-16 rounded-pill bg-success-soft text-success mb-4">
        <Icon name="heroicons:check" class="w-8 h-8" />
      </span>
      <h1 class="text-lg font-bold mb-1">Заявка отправлена</h1>
      <p v-if="createdOrder" class="text-sm text-ink-muted mb-6"> №{{ shortId(createdOrder.id) }} · {{ formatMoney(createdOrder.total_amount, createdOrder.currency_code) }}</p>
      <NuxtLink to="/m/orders" class="btn-primary w-full justify-center py-3">Мои заявки</NuxtLink>
      <NuxtLink to="/m/catalog" class="btn-ghost w-full justify-center py-2.5 mt-2">В каталог</NuxtLink>
    </div>
  </div>
</template>
