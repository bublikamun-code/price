<script setup lang="ts">
// Профиль клиента (менеджер): профиль, матрица скидок, фикс. курс, последние заказы.
// Этап 8. См. SITEMAP.md /manager/users/{id}, ARCHITECTURE_PLAN.md §6.
import type {
  DiscountOut,
  OrderListPage,
  OrderRead,
  OrderStatus,
  RateOut,
  TempPasswordOut,
  UserManagerDetail,
  UserManagerRead,
} from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER'] })

const route = useRoute()
const { request } = useApi()
const userId = computed(() => String(route.params.id))

const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

const CURRENCIES = ['BYN', 'USD', 'EUR', 'RUB'] as const
const FIX_CURRENCIES = ['USD', 'EUR', 'RUB'] as const
type FixCurrency = (typeof FIX_CURRENCIES)[number]

// --- Загрузка деталей ---
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const detail = ref<UserManagerDetail | null>(null)

useHead({ title: computed(() => `Клиент ${detail.value?.user.full_name ?? ''} — Менеджер`) })

// Одноразовое success-уведомление (авто-скрытие через 4 с).
function useFlash(timeout = 4000) {
  const msg = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  function flash(text: string) {
    msg.value = text
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => (msg.value = ''), timeout)
  }
  onUnmounted(() => {
    if (timer) clearTimeout(timer)
  })
  return { msg, flash }
}

const { msg: profileMsg, flash: flashProfile } = useFlash()
const { msg: discountMsg, flash: flashDiscount } = useFlash()
const { msg: fixedMsg, flash: flashFixed } = useFlash()

function isFixCurrency(v: string): v is FixCurrency {
  return (FIX_CURRENCIES as readonly string[]).includes(v)
}

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    detail.value = await request<UserManagerDetail>(`/api/v1/manager/users/${userId.value}`)
    syncProfile()
    syncDiscounts()
    syncFixedForm()
  } catch (e) {
    if (getErrorStatus(e) === 404) notFound.value = true
    else error.value = getErrorMessage(e, 'Не удалось загрузить клиента')
  } finally {
    loading.value = false
  }
}

function formatDate(s: string): string {
  // fetched_at фиксированного курса — дата без времени (YYYY-MM-DD), парсим как локальную.
  return new Date(s.length === 10 ? `${s}T00:00:00` : s).toLocaleDateString('ru-RU')
}
function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}
function shortId(id: string): string {
  return id.slice(0, 8)
}

// --- Профиль ---
const profile = reactive({
  full_name: '',
  company: '',
  phone: '',
  display_currency: 'BYN',
  is_active: true,
})
const profileSaving = ref(false)
const profileError = ref('')

function syncProfile() {
  const u = detail.value?.user
  if (!u) return
  profile.full_name = u.full_name
  profile.company = u.company ?? ''
  profile.phone = u.phone ?? ''
  profile.display_currency = u.display_currency
  profile.is_active = u.is_active
}

async function saveProfile() {
  if (!detail.value || profileSaving.value) return
  profileSaving.value = true
  profileError.value = ''
  try {
    const user = await request<UserManagerRead>(`/api/v1/manager/users/${userId.value}`, {
      method: 'PATCH',
      body: {
        full_name: profile.full_name.trim(),
        company: profile.company.trim() || null,
        phone: profile.phone.trim() || null,
        display_currency: profile.display_currency,
        is_active: profile.is_active,
      },
    })
    detail.value.user = user
    flashProfile('Профиль сохранён')
  } catch (e) {
    profileError.value = getErrorMessage(e, 'Не удалось сохранить профиль')
  } finally {
    profileSaving.value = false
  }
}

// --- Сброс пароля ---
const resettingPassword = ref(false)
const resetError = ref('')
const tempPassword = ref('')

async function resetPassword() {
  if (resettingPassword.value) return
  const email = detail.value?.user.email ?? ''
  if (!window.confirm(`Сбросить пароль клиента ${email}? Все его текущие сессии будут завершены.`)) return
  resettingPassword.value = true
  resetError.value = ''
  try {
    const res = await request<TempPasswordOut>(`/api/v1/manager/users/${userId.value}/reset-password`, {
      method: 'POST',
    })
    tempPassword.value = res.temp_password
  } catch (e) {
    resetError.value = getErrorMessage(e, 'Не удалось сбросить пароль')
  } finally {
    resettingPassword.value = false
  }
}

// --- Матрица скидок ---
interface DiscountRow {
  brand_id: string
  brand_name: string
  percent: string
}

const discountRows = ref<DiscountRow[]>([])
const applyAllValue = ref('')
const applyAllError = ref('')
const discountsSaving = ref(false)
const discountsError = ref('')

function validPercent(v: string): boolean {
  const n = Number(v)
  return v.trim() !== '' && !Number.isNaN(n) && n >= 0 && n <= 100
}

function syncDiscounts() {
  discountRows.value = (detail.value?.discounts ?? []).map((d) => ({
    brand_id: d.brand_id,
    brand_name: d.brand_name,
    percent: d.percent,
  }))
}

function applyToAll() {
  const v = applyAllValue.value.trim()
  if (!validPercent(v)) {
    applyAllError.value = 'Введите процент от 0 до 100'
    return
  }
  applyAllError.value = ''
  discountRows.value = discountRows.value.map((r) => ({ ...r, percent: v }))
}

async function saveDiscounts() {
  if (discountsSaving.value) return
  if (discountRows.value.some((r) => !validPercent(r.percent))) {
    discountsError.value = 'Процент должен быть числом от 0 до 100'
    return
  }
  discountsSaving.value = true
  discountsError.value = ''
  try {
    // Полная матрица, включая нули (контракт этапа 8).
    const res = await request<DiscountOut[]>(`/api/v1/manager/users/${userId.value}/discounts`, {
      method: 'PUT',
      body: {
        discounts: discountRows.value.map((r) => ({ brand_id: r.brand_id, percent: r.percent.trim() })),
      },
    })
    detail.value!.discounts = res
    syncDiscounts()
    flashDiscount('Скидки сохранены')
  } catch (e) {
    discountsError.value = getErrorMessage(e, 'Не удалось сохранить скидки')
  } finally {
    discountsSaving.value = false
  }
}

// --- Зафиксированный курс ---
const fixCurrency = ref<FixCurrency>('USD')
const fixMode = ref<'manual' | 'nbrb'>('nbrb')
const fixRate = ref('')
const fixing = ref(false)
const unfixing = ref(false)
const fixError = ref('')

function syncFixedForm() {
  const fr = detail.value?.user.fixed_rate
  if (!fr) return
  if (isFixCurrency(fr.currency_code)) fixCurrency.value = fr.currency_code
  fixMode.value = fr.is_manual ? 'manual' : 'nbrb'
  fixRate.value = fr.rate
}

function sourceLabel(r: RateOut): string {
  return r.source === 'MANUAL' ? 'Вручную' : 'НБ РБ'
}

async function applyFixedRate() {
  if (fixing.value) return
  if (fixMode.value === 'manual' && !validRate(fixRate.value)) {
    fixError.value = 'Введите курс (положительное число)'
    return
  }
  fixing.value = true
  fixError.value = ''
  try {
    const body: Record<string, unknown> = { currency_code: fixCurrency.value }
    if (fixMode.value === 'manual') body.rate = fixRate.value.trim()
    const user = await request<UserManagerRead>(`/api/v1/manager/users/${userId.value}/fixed-rate`, {
      method: 'PUT',
      body,
    })
    detail.value!.user = user
    syncFixedForm()
    flashFixed('Курс зафиксирован')
  } catch (e) {
    // 409 — нет курса НБ РБ для валюты; текст придёт из detail.
    fixError.value = getErrorMessage(e, 'Не удалось зафиксировать курс')
  } finally {
    fixing.value = false
  }
}

async function resetFixedRate() {
  if (unfixing.value) return
  if (!window.confirm('Снять зафиксированный курс? Цены клиента будут считаться по текущему курсу НБ РБ.')) return
  unfixing.value = true
  fixError.value = ''
  try {
    const user = await request<UserManagerRead>(`/api/v1/manager/users/${userId.value}/fixed-rate`, {
      method: 'PUT',
      body: { reset: true },
    })
    detail.value!.user = user
    flashFixed('Фиксация снята')
  } catch (e) {
    fixError.value = getErrorMessage(e, 'Не удалось снять фиксацию курса')
  } finally {
    unfixing.value = false
  }
}

function validRate(v: string): boolean {
  const n = Number(v)
  return v.trim() !== '' && !Number.isNaN(n) && n > 0
}

// --- Последние заказы ---
const orders = ref<OrderRead[]>([])
const ordersLoading = ref(true)
const ordersError = ref('')

async function loadOrders() {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const res = await request<OrderListPage>('/api/v1/manager/orders', {
      query: { client: userId.value, page: 1, per_page: 5 },
    })
    orders.value = res.data
  } catch (e) {
    ordersError.value = getErrorMessage(e, 'Не удалось загрузить заказы')
  } finally {
    ordersLoading.value = false
  }
}

onMounted(() => {
  load()
  loadOrders()
})
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/manager/users" class="hover:text-primary">Клиенты</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Профиль</span>
    </nav>

    <div v-if="loading" class="space-y-4">
      <div class="skeleton h-16 w-72"/>
      <div class="skeleton h-64 w-full"/>
      <div class="skeleton h-64 w-full"/>
    </div>

    <div v-else-if="notFound" class="card p-12 text-center">
      <Icon name="heroicons:user" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Клиент не найден</p>
      <NuxtLink to="/manager/users" class="btn-primary">К списку клиентов</NuxtLink>
    </div>

    <div v-else-if="error && !detail" class="card p-8 text-center">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div><button class="btn-primary" @click="load">Повторить</button></div>
    </div>

    <template v-else-if="detail">
      <!-- Шапка -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div class="min-w-0">
          <div class="flex items-center gap-3 mb-1">
            <h1 class="text-2xl font-bold truncate">{{ detail.user.full_name }}</h1>
            <span v-if="detail.user.is_active" class="badge-success shrink-0">Активен</span>
            <span v-else class="badge-danger shrink-0">Заблокирован</span>
          </div>
          <p class="text-sm text-ink-muted truncate">
            {{ detail.user.email }} · создан {{ formatDate(detail.user.created_at) }}
          </p>
        </div>
      </div>

      <!-- Профиль -->
      <div class="card p-6 mb-6">
        <h2 class="font-semibold mb-4">Профиль</h2>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="label" for="p-name">ФИО</label>
            <input id="p-name" v-model="profile.full_name" type="text" class="input">
          </div>
          <div>
            <label class="label" for="p-company">Компания</label>
            <input id="p-company" v-model="profile.company" type="text" class="input">
          </div>
          <div>
            <label class="label" for="p-phone">Телефон</label>
            <input id="p-phone" v-model="profile.phone" type="tel" class="input">
          </div>
          <div>
            <label class="label" for="p-currency">Валюта отображения</label>
            <select id="p-currency" v-model="profile.display_currency" class="input py-2.5">
              <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>

        <label class="flex items-center gap-3 cursor-pointer select-none mt-5">
          <input v-model="profile.is_active" type="checkbox" class="w-4 h-4 accent-primary">
          <span class="text-sm font-medium">Активен</span>
          <span class="text-xs text-ink-faint">Блокировка запрещает вход в портал</span>
        </label>

        <div v-if="profileError" class="badge-danger w-full justify-center py-2 mt-5">{{ profileError }}</div>
        <div v-if="resetError" class="badge-danger w-full justify-center py-2 mt-5">{{ resetError }}</div>
        <div v-if="profileMsg" class="badge-success w-full justify-center py-2 mt-5">
          <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ profileMsg }}
        </div>

        <div class="flex flex-wrap justify-end gap-2 mt-6">
          <button
            class="btn-outline"
            :disabled="resettingPassword"
            @click="resetPassword"
          >
            <span v-if="resettingPassword" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
            <Icon v-else name="heroicons:key" class="w-4 h-4" />
            Сбросить пароль
          </button>
          <button class="btn-primary" :disabled="profileSaving" @click="saveProfile">
            <span v-if="profileSaving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            {{ profileSaving ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </div>

      <!-- Матрица скидок -->
      <div class="card p-6 mb-6">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <h2 class="font-semibold">Матрица скидок</h2>
          <div class="flex items-center gap-2">
            <span class="text-sm text-ink-muted whitespace-nowrap">Применить ко всем:</span>
            <input
              v-model="applyAllValue"
              type="number"
              min="0"
              max="100"
              step="0.5"
              placeholder="%"
              class="input w-24 py-2 text-center"
              @keyup.enter="applyToAll"
            >
            <button type="button" class="btn-outline py-2" @click="applyToAll">Применить</button>
          </div>
        </div>

        <div v-if="applyAllError" class="badge-danger mb-3">{{ applyAllError }}</div>

        <div v-if="discountRows.length" class="max-h-96 overflow-y-auto border border-border/60 rounded-card">
          <table class="w-full text-sm">
            <thead class="sticky top-0">
              <tr class="text-ink-muted text-left bg-canvas">
                <th class="px-4 py-3 font-medium">Бренд</th>
                <th class="px-4 py-3 font-medium text-right w-40">Скидка, %</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in discountRows" :key="row.brand_id" class="border-t border-border">
                <td class="px-4 py-2.5">{{ row.brand_name }}</td>
                <td class="px-4 py-2.5 text-right">
                  <input
                    v-model="row.percent"
                    type="number"
                    min="0"
                    max="100"
                    step="0.5"
                    class="input w-28 py-1.5 text-right"
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-sm text-ink-muted">Брендов пока нет — скидки настраиваются после импорта каталога.</p>

        <div v-if="discountsError" class="badge-danger w-full justify-center py-2 mt-5">{{ discountsError }}</div>
        <div v-if="discountMsg" class="badge-success w-full justify-center py-2 mt-5">
          <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ discountMsg }}
        </div>

        <div v-if="discountRows.length" class="flex justify-end mt-5">
          <button class="btn-primary" :disabled="discountsSaving" @click="saveDiscounts">
            <span v-if="discountsSaving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            {{ discountsSaving ? 'Сохранение…' : 'Сохранить скидки' }}
          </button>
        </div>
      </div>

      <!-- Зафиксированный курс -->
      <div class="card p-6 mb-6">
        <h2 class="font-semibold mb-4">Зафиксированный курс</h2>

        <div v-if="detail.user.fixed_rate" class="flex flex-wrap items-center gap-x-4 gap-y-2 mb-5 p-4 rounded-card bg-canvas border border-border/60">
          <span class="font-semibold">{{ detail.user.fixed_rate.currency_code }}</span>
          <span class="font-mono">{{ detail.user.fixed_rate.rate }}</span>
          <span :class="detail.user.fixed_rate.is_manual ? 'badge-warning' : 'badge-info'">
            {{ sourceLabel(detail.user.fixed_rate) }}
          </span>
          <span class="text-sm text-ink-muted">от {{ formatDate(detail.user.fixed_rate.fetched_at) }}</span>
        </div>
        <p v-else class="text-sm text-ink-muted mb-5">Не зафиксирован — цены считаются по текущему курсу НБ РБ.</p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="label" for="fx-currency">Валюта</label>
            <select id="fx-currency" v-model="fixCurrency" class="input py-2.5">
              <option v-for="c in FIX_CURRENCIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
          <div>
            <span class="label">Режим</span>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="px-3.5 py-2 rounded-pill text-sm font-medium transition-colors"
                :class="fixMode === 'manual' ? 'bg-primary text-white' : 'bg-surface border border-border text-ink-muted hover:border-primary/60'"
                @click="fixMode = 'manual'"
              >Вручную</button>
              <button
                type="button"
                class="px-3.5 py-2 rounded-pill text-sm font-medium transition-colors"
                :class="fixMode === 'nbrb' ? 'bg-primary text-white' : 'bg-surface border border-border text-ink-muted hover:border-primary/60'"
                @click="fixMode = 'nbrb'"
              >По текущему курсу НБ РБ</button>
            </div>
          </div>
          <div v-if="fixMode === 'manual'">
            <label class="label" for="fx-rate">Курс за 1 ед. (в BYN)</label>
            <input id="fx-rate" v-model="fixRate" type="number" min="0" step="0.0001" class="input" placeholder="Напр. 3.27">
          </div>
        </div>

        <div v-if="fixError" class="badge-danger w-full justify-center py-2 mt-5">{{ fixError }}</div>
        <div v-if="fixedMsg" class="badge-success w-full justify-center py-2 mt-5">
          <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ fixedMsg }}
        </div>

        <div class="flex flex-wrap justify-end gap-2 mt-6">
          <button
            v-if="detail.user.fixed_rate"
            class="btn-ghost text-danger"
            :disabled="unfixing"
            @click="resetFixedRate"
          >
            <span v-if="unfixing" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
            <Icon v-else name="heroicons:arrow-uturn-left" class="w-4 h-4" />
            Снять фиксацию
          </button>
          <button class="btn-primary" :disabled="fixing" @click="applyFixedRate">
            <span v-if="fixing" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            {{ fixing ? 'Фиксация…' : 'Зафиксировать' }}
          </button>
        </div>
      </div>

      <!-- Последние заказы -->
      <div class="card p-6">
        <h2 class="font-semibold mb-4">Последние заказы</h2>

        <div v-if="ordersError" class="flex items-center gap-3 mb-4">
          <div class="badge-danger">{{ ordersError }}</div>
          <button class="btn-ghost text-sm" @click="loadOrders">Повторить</button>
        </div>

        <div v-if="ordersLoading" class="space-y-3">
          <div v-for="i in 3" :key="i" class="skeleton h-12 w-full"/>
        </div>

        <p v-else-if="!orders.length" class="text-sm text-ink-muted">Заказов пока нет.</p>

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-canvas">
                <th class="px-4 py-3 font-medium">№</th>
                <th class="px-4 py-3 font-medium">Дата</th>
                <th class="px-4 py-3 font-medium">Статус</th>
                <th class="px-4 py-3 font-medium text-right">Сумма</th>
                <th class="px-4 py-3 font-medium text-right">Действие</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in orders" :key="o.id" class="border-t border-border hover:bg-canvas/60">
                <td class="px-4 py-3 font-mono text-xs" :title="o.id">№{{ shortId(o.id) }}</td>
                <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDateTime(o.created_at) }}</td>
                <td class="px-4 py-3">
                  <span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span>
                </td>
                <td class="px-4 py-3 text-right font-semibold whitespace-nowrap">
                  {{ o.total_amount }} {{ o.currency_code }}
                </td>
                <td class="px-4 py-3 text-right">
                  <NuxtLink :to="`/manager/orders/${o.id}`" class="btn-ghost text-sm py-1.5">
                    <Icon name="heroicons:eye" class="w-4 h-4" /> Открыть
                  </NuxtLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- Временный пароль после сброса -->
    <TempPasswordDialog v-if="tempPassword" :password="tempPassword" @close="tempPassword = ''"/>
  </div>
</template>
