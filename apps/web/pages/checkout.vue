<script setup lang="ts">
// Оформление заявки. См. SITEMAP.md §6, §9 (снапшот цен/курса при POST /orders).
import type { OrderCreate, OrderRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Оформление заявки' })

const { request } = useApi()
const { photoOf } = useProductPhoto()
const { data: cartData, loading, refresh, clear } = useCart()

const notes = ref('')
const submitting = ref(false)
const error = ref('')

const currency = computed(() => cartData.value?.items[0]?.currency || 'BYN')

async function submit() {
  if (!cartData.value?.items.length || submitting.value) return
  submitting.value = true
  error.value = ''
  const payload: OrderCreate = {
    items: cartData.value.items.map((i) => ({ sku: i.sku, quantity: i.quantity, note: i.note })),
    notes: notes.value || null,
    price_calc_mode: 'fixed',
  }
  try {
    const order = await request<OrderRead>('/api/v1/orders', { method: 'POST', body: payload })
    await clear() // после оформления корзина не нужна
    await navigateTo(`/orders/${order.id}`)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось оформить заявку')
  } finally {
    submitting.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/cart" class="hover:text-primary">Корзина</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Оформление</span>
    </nav>

    <h1 class="text-2xl font-bold mb-6">Оформление заявки</h1>

    <div v-if="loading && !cartData" class="card p-5">
      <div class="skeleton h-24 w-full"/>
    </div>

    <div v-else-if="!cartData || !cartData.total_items" class="card p-12 text-center">
      <Icon name="heroicons:shopping-cart" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Корзина пуста — нечего оформлять</p>
      <NuxtLink to="/catalog" class="btn-primary">В каталог</NuxtLink>
    </div>

    <div v-else class="grid lg:grid-cols-3 gap-6 items-start">
      <!-- Позиции (read-only) -->
      <div class="lg:col-span-2 space-y-3">
        <div class="card overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-canvas">
                <th class="px-4 py-3 font-medium">Товар</th>
                <th class="px-4 py-3 font-medium text-center">Кол-во</th>
                <th class="px-4 py-3 font-medium text-right">Цена</th>
                <th class="px-4 py-3 font-medium text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in cartData.items" :key="item.product_id" class="border-t border-border">
                <td class="px-4 py-3">
                  <div class="flex items-center gap-3">
                    <div class="w-10 h-10 shrink-0 rounded-card bg-canvas overflow-hidden flex items-center justify-center">
                      <img v-if="photoOf(item)" :src="photoOf(item)!" :alt="item.name" class="w-full h-full object-contain" >
                      <Icon v-else name="heroicons:photo" class="w-5 h-5 text-ink-faint" />
                    </div>
                    <div class="min-w-0">
                      <p class="font-medium line-clamp-1">{{ item.name }}</p>
                      <p class="text-xs text-ink-faint">{{ item.sku }}</p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 text-center">{{ item.quantity }}</td>
                <td class="px-4 py-3 text-right">{{ item.unit_price }} {{ item.currency }}</td>
                <td class="px-4 py-3 text-right font-medium">{{ item.line_total }} {{ item.currency }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Форма -->
      <aside class="lg:sticky lg:top-[88px]">
        <div class="card p-6">
          <h3 class="font-semibold mb-4">Параметры заявки</h3>

          <div v-if="currency !== 'BYN'" class="badge-info w-full justify-center py-2 mb-4">
            <Icon name="heroicons:information-circle" class="w-4 h-4" />
            Курс {{ currency }} будет зафиксирован при отправке
          </div>

          <label class="label" for="notes">Комментарий к заказу</label>
          <textarea
            id="notes"
            v-model="notes"
            rows="3"
            class="input py-2.5 resize-y"
            placeholder="Сертификат, сроки доставки, особые пожелания…"
          />

          <div class="flex justify-between text-lg font-bold py-3 border-t border-border mt-4">
            <span>Итого</span>
            <span>{{ cartData.total_amount }} <span class="text-sm font-normal text-ink-muted">{{ currency }}</span></span>
          </div>

          <div v-if="error" class="badge-danger w-full justify-center py-2 mt-2">{{ error }}</div>

          <button
            class="btn-primary w-full justify-center py-3 mt-3"
            :disabled="submitting"
            @click="submit"
          >
            <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            <Icon v-else name="heroicons:paper-airplane" class="w-4 h-4" />
            {{ submitting ? 'Отправка…' : 'Отправить заявку' }}
          </button>
          <NuxtLink to="/cart" class="btn-ghost w-full justify-center mt-2">Назад в корзину</NuxtLink>
        </div>
      </aside>
    </div>
  </div>
</template>
