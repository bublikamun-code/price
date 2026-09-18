<script setup lang="ts">
// Оформление заявки. См. SITEMAP.md §6, §9 (снапшот цен/курса при POST /orders).
import type { OrderCreate, OrderRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Оформление заявки' })

const { request } = useApi()
const { thumbOf } = useProductPhoto()
const { data: cartData, loading, refresh } = useCart()

// Способы получения (список пунктов самовывоза расширится позже).
type DeliveryMethod = 'pickup' | 'delivery'
const PICKUP_POINTS: { id: string; label: string }[] = [
  { id: 'main', label: 'г. Минск, пр. Дзержинского, 104 (склад)' },
]

const deliveryMethod = ref<DeliveryMethod>('pickup')
const pickupPointId = ref<string>(PICKUP_POINTS[0]!.id)

const deliveryPoint = computed(() => {
  if (deliveryMethod.value !== 'pickup') return null
  return PICKUP_POINTS.find((p) => p.id === pickupPointId.value)?.label ?? null
})

// Поля доставки (показываются при deliveryMethod === 'delivery').
const deliveryAddress = ref('')
const deliveryContact = ref('')
const deliveryPhone = ref('')
const deliveryComment = ref('')

const notes = ref('')
const submitting = ref(false)
const error = ref('')

const currency = computed(() => cartData.value?.items[0]?.currency || 'BYN')

async function submit() {
  if (!cartData.value?.items.length || submitting.value) return

  // Валидация адреса доставки.
  if (deliveryMethod.value === 'delivery' && !deliveryAddress.value.trim()) {
    error.value = 'Укажите адрес доставки'
    return
  }

  submitting.value = true
  error.value = ''

  // Собираем информацию о доставке в notes для бэкенда.
  const deliveryNotes: string[] = []
  if (deliveryMethod.value === 'delivery') {
    deliveryNotes.push(`Адрес доставки: ${deliveryAddress.value.trim()}`)
    if (deliveryContact.value.trim()) deliveryNotes.push(`Контактное лицо: ${deliveryContact.value.trim()}`)
    if (deliveryPhone.value.trim()) deliveryNotes.push(`Телефон для доставки: ${deliveryPhone.value.trim()}`)
    if (deliveryComment.value.trim()) deliveryNotes.push(`Комментарий к доставке: ${deliveryComment.value.trim()}`)
  }
  const combinedNotes = [
    ...deliveryNotes,
    ...(notes.value.trim() ? [notes.value.trim()] : []),
  ].join('\n') || null

  const payload: OrderCreate = {
    items: cartData.value.items.map((i) => ({ sku: i.sku, quantity: i.quantity, note: i.note })),
    notes: combinedNotes,
    price_calc_mode: 'fixed',
    // Поля получения: бэкенд примет их параллельно с этой правкой.
    delivery_method: deliveryMethod.value,
    delivery_point: deliveryPoint.value,
    delivery_address: deliveryMethod.value === 'delivery' ? deliveryAddress.value.trim() : null,
    delivery_contact: deliveryMethod.value === 'delivery' ? deliveryContact.value.trim() || null : null,
    delivery_phone: deliveryMethod.value === 'delivery' ? deliveryPhone.value.trim() || null : null,
    delivery_comment: deliveryMethod.value === 'delivery' ? deliveryComment.value.trim() || null : null,
  } as OrderCreate
  try {
    const order = await request<OrderRead>('/api/v1/orders', { method: 'POST', body: payload })
    // Корзина очищается на бэке атомарно при создании заявки.
    // Обновляем локальный стейт чтобы счётчик в хедере сбросился.
    await refresh()
    await navigateTo(`/orders/${order.id}`)
  } catch (e) {
    // 422 по остаткам: показываем детали бэка («По позиции <sku> доступно только N шт»).
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
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
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
                      <img v-if="thumbOf(item.photo_key)" :src="thumbOf(item.photo_key)!" :alt="item.name" class="w-full h-full object-contain" >
                      <Icon v-else name="heroicons:photo" class="w-5 h-5 text-ink-faint" />
                    </div>
                    <div class="min-w-0">
                      <p class="font-medium line-clamp-1">{{ item.name }}</p>
                      <p class="text-xs text-ink-faint">{{ item.sku }}</p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 text-center">{{ item.quantity }}</td>
                <td class="px-4 py-3 text-right">{{ formatMoney(item.unit_price, item.currency) }}</td>
                <td class="px-4 py-3 text-right font-medium">{{ formatMoney(item.line_total, item.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Способ получения -->
        <fieldset class="card p-5">
        <legend class="sr-only">Способ получения</legend>
        <h3 class="font-semibold mb-4">Получение</h3>
        <div class="grid sm:grid-cols-2 gap-3">
          <!-- Самовывоз -->
          <label
            class="flex gap-3 p-4 rounded-card border cursor-pointer transition-colors"
            :class="deliveryMethod === 'pickup' ? 'border-primary bg-primary-soft/30' : 'border-border hover:border-primary/50'"
          >
            <input v-model="deliveryMethod" type="radio" value="pickup" name="delivery_method" class="mt-0.5 accent-primary">
            <span class="min-w-0">
              <span class="block text-sm font-semibold">Самовывоз</span>
              <span class="block text-xs text-ink-muted mt-0.5">Бесплатно.</span>
              <template v-if="deliveryMethod === 'pickup'">
                <select v-model="pickupPointId" class="input mt-2 text-sm py-1.5" @click.stop>
                  <option v-for="p in PICKUP_POINTS" :key="p.id" :value="p.id">{{ p.label }}</option>
                </select>
              </template>
            </span>
          </label>

          <!-- Доставка -->
          <label
            class="flex gap-3 p-4 rounded-card border cursor-pointer transition-colors"
            :class="deliveryMethod === 'delivery' ? 'border-primary bg-primary-soft/30' : 'border-border hover:border-primary/50'"
          >
            <input v-model="deliveryMethod" type="radio" value="delivery" name="delivery_method" class="mt-0.5 accent-primary">
            <span class="min-w-0">
              <span class="block text-sm font-semibold">Доставка</span>
              <span class="block text-xs text-ink-muted mt-0.5">Условия и стоимость согласует менеджер.</span>
            </span>
          </label>
        </div>

        <!-- Поля доставки (показываются при выборе «Доставка») -->
        <div v-if="deliveryMethod === 'delivery'" class="mt-4 space-y-3">
          <div>
            <label class="label" for="delivery-address">Адрес доставки <span class="text-danger">*</span></label>
            <input
              id="delivery-address"
              v-model="deliveryAddress"
              type="text"
              class="input"
              placeholder="г. Минск, ул. Примерная, д. 1, офис 1"
              required
            >
          </div>
          <div class="grid sm:grid-cols-2 gap-3">
            <div>
              <label class="label" for="delivery-contact">Контактное лицо</label>
              <input
                id="delivery-contact"
                v-model="deliveryContact"
                type="text"
                class="input"
                placeholder="Иванов Иван"
              >
            </div>
            <div>
              <label class="label" for="delivery-phone">Телефон для доставки</label>
              <input
                id="delivery-phone"
                v-model="deliveryPhone"
                type="tel"
                class="input"
                placeholder="+375 29 000-00-00"
              >
            </div>
          </div>
          <div>
            <label class="label" for="delivery-comment">Комментарий к доставке</label>
            <textarea
              id="delivery-comment"
              v-model="deliveryComment"
              class="input min-h-20 resize-y"
              placeholder="Время приёмки, пропуск, и т.д."
            />
          </div>
        </div>
      </fieldset>
    </div>
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
            <span>{{ formatMoney(cartData.total_amount, currency) }}</span>
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
