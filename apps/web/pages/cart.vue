<script setup lang="ts">
// Корзина клиента (persist в БД). См. SITEMAP.md §6, ARCHITECTURE_PLAN.md §19.
import type { CartItemRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Корзина' })

const { thumbOf } = useProductPhoto()
const { data: cart, loading, refresh, update, remove, clear } = useCart()
const error = ref('')
const updatingSku = ref<string | null>(null)
const removingSku = ref<string | null>(null)

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

async function saveNote(item: CartItemRead, e: Event) {
  const note = (e.target as HTMLInputElement).value
  try {
    await update(item.sku, { note })
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось сохранить заметку')
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

async function clearAll() {
  if (!confirm('Очистить корзину?')) return
  error.value = ''
  try {
    await clear()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось очистить корзину')
  }
}

onMounted(refresh)
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold">Корзина</h1>
        <p class="text-sm text-ink-muted mt-1">
          <template v-if="cart">{{ cart.total_items }} {{ pluralize(cart.total_items, 'позиция', 'позиции', 'позиций') }}</template>
          <template v-else>Загрузка…</template>
        </p>
      </div>
      <button v-if="cart && cart.total_items" class="btn-ghost text-danger" @click="clearAll">
        <Icon name="heroicons:trash" class="w-4 h-4" /> Очистить
      </button>
    </div>

    <div v-if="error" class="badge-danger w-full justify-center py-3 mb-6">{{ error }}</div>

    <!-- Skeleton -->
    <div v-if="loading && !cart" class="space-y-3">
      <div v-for="i in 3" :key="i" class="card p-4">
        <div class="skeleton h-20 w-full"/>
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="!cart || !cart.total_items" class="card p-12 text-center">
      <Icon name="heroicons:shopping-cart" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Корзина пуста</p>
      <NuxtLink to="/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
    </div>

    <!-- Содержимое -->
    <div v-else class="grid lg:grid-cols-3 gap-6 items-start">
      <!-- Позиции -->
      <div class="lg:col-span-2 space-y-3">
        <article
          v-for="item in cart.items"
          :key="item.product_id"
          class="card p-4 flex gap-4"
        >
          <!-- Фото -->
          <div class="w-20 h-20 shrink-0 rounded-card bg-canvas overflow-hidden flex items-center justify-center">
            <img v-if="thumbOf(item.photo_key)" :src="thumbOf(item.photo_key)!" :alt="item.name" class="w-full h-full object-contain" >
            <Icon v-else name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
          </div>

          <!-- Инфо -->
          <div class="flex-1 min-w-0">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <NuxtLink :to="`/catalog/${item.sku}`" class="font-medium hover:text-primary line-clamp-1">
                  {{ item.name }}
                </NuxtLink>
                <p class="text-xs text-ink-faint mt-0.5">Артикул: {{ item.sku }}<span v-if="item.brand_name"> · {{ item.brand_name }}</span></p>
              </div>
              <button
                class="btn-ghost p-1.5 text-ink-faint hover:text-danger shrink-0"
                :disabled="removingSku === item.sku"
                title="Удалить"
                @click="removeItem(item)"
              >
                <span v-if="removingSku === item.sku" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                <Icon v-else name="heroicons:trash" class="w-4 h-4" />
              </button>
            </div>

            <!-- Заметка -->
            <input
              :value="item.note"
              type="text"
              placeholder="Заметка к позиции…"
              class="input py-1.5 mt-2 text-xs"
              @blur="saveNote(item, $event)"
            >

            <!-- Цена + stepper -->
            <div class="flex items-center justify-between gap-3 mt-3">
              <div class="flex items-center gap-1">
                <button class="btn-outline px-2.5 py-1" :disabled="updatingSku === item.sku" @click="changeQty(item, -1)">
                  <Icon name="heroicons:minus" class="w-3.5 h-3.5" />
                </button>
                <span class="w-10 text-center font-medium">{{ item.quantity }}</span>
                <button class="btn-outline px-2.5 py-1" :disabled="updatingSku === item.sku" @click="changeQty(item, 1)">
                  <Icon name="heroicons:plus" class="w-3.5 h-3.5" />
                </button>
              </div>
              <div class="text-right">
                <p class="text-sm text-ink-muted">{{ formatMoney(item.unit_price, item.currency) }} / шт</p>
                <p class="font-bold">{{ formatMoney(item.line_total, item.currency) }}</p>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- Сводка -->
      <aside class="lg:sticky lg:top-[88px]">
        <div class="card p-6">
          <h3 class="font-semibold mb-4">Итого</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Позиций</span>
            <span class="font-medium">{{ cart.total_items }}</span>
          </div>
          <div class="flex justify-between text-lg font-bold py-2 border-t border-border mt-2">
            <span>Сумма</span>
            <span>{{ formatMoney(cart.total_amount, cart.items[0]?.currency) }}</span>
          </div>
          <NuxtLink to="/checkout" class="btn-primary w-full justify-center py-3 mt-4">
            <Icon name="heroicons:document-check" class="w-4 h-4" /> Оформить заявку
          </NuxtLink>
          <NuxtLink to="/catalog" class="btn-ghost w-full justify-center mt-2">Продолжить покупки</NuxtLink>
        </div>
      </aside>
    </div>
  </div>
</template>
