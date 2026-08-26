<script setup lang="ts">
// Курсы валют (менеджер): история за 7 дней, ручной курс, обновление НБ РБ. Этап 8.
// GET/POST /api/v1/manager/currencies/rate(s), POST /manager/currencies/refresh.
import type { RateOut } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Курсы валют — Менеджер' })

const { request } = useApi()

const FIX_CURRENCIES = ['USD', 'EUR', 'RUB'] as const
type FixCurrency = (typeof FIX_CURRENCIES)[number]

const CURRENCY_META: Record<string, { label: string }> = {
  USD: { label: 'USD — Доллар США' },
  EUR: { label: 'EUR — Евро' },
  RUB: { label: 'RUB — Российский рубль' },
}

// --- История курсов (за 7 дней, все источники) ---
const loading = ref(true)
const error = ref('')
const rates = ref<RateOut[]>([])

// Валюта по алфавиту, внутри — свежие даты сверху.
const sortedRates = computed(() =>
  [...rates.value].sort(
    (a, b) =>
      a.currency_code.localeCompare(b.currency_code) || b.fetched_at.localeCompare(a.fetched_at),
  ),
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<{ data: RateOut[] }>('/api/v1/manager/currencies/rates')
    rates.value = res.data
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить курсы валют')
  } finally {
    loading.value = false
  }
}

function sourceLabel(r: RateOut): string {
  return r.source === 'MANUAL' ? 'Вручную' : 'НБ РБ'
}

function formatDate(s: string): string {
  // fetched_at — дата без времени (YYYY-MM-DD), парсим как локальную.
  return new Date(s.length === 10 ? `${s}T00:00:00` : s).toLocaleDateString('ru-RU')
}

// --- Обновление курсов НБ РБ (фоновая задача, 202) ---
const refreshing = ref(false)
const refreshError = ref('')
const refreshMsg = ref('')
let refreshTimer: ReturnType<typeof setTimeout> | null = null

async function refreshRates() {
  if (refreshing.value) return
  refreshing.value = true
  refreshError.value = ''
  refreshMsg.value = ''
  try {
    await request<{ queued: boolean }>('/api/v1/manager/currencies/refresh', { method: 'POST' })
    refreshMsg.value = 'Обновление запрошено — курсы обновятся в течение минуты'
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => (refreshMsg.value = ''), 5000)
  } catch (e) {
    refreshError.value = getErrorMessage(e, 'Не удалось запросить обновление курсов')
  } finally {
    refreshing.value = false
  }
}

// --- Ручной курс ---
function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

const manualForm = reactive({
  currency_code: 'USD' as FixCurrency,
  rate: '',
  fetched_at: todayIso(),
})
const manualSaving = ref(false)
const manualError = ref('')
const manualMsg = ref('')
let manualTimer: ReturnType<typeof setTimeout> | null = null

const manualValid = computed(() => manualForm.rate.trim() !== '' && Number(manualForm.rate) > 0)

async function submitManual() {
  if (!manualValid.value || manualSaving.value) return
  manualSaving.value = true
  manualError.value = ''
  manualMsg.value = ''
  try {
    await request<RateOut>('/api/v1/manager/currencies/rate', {
      method: 'POST',
      body: {
        currency_code: manualForm.currency_code,
        rate: manualForm.rate.trim(),
        fetched_at: manualForm.fetched_at,
      },
    })
    manualMsg.value = `Курс ${manualForm.currency_code} добавлен`
    manualForm.rate = ''
    await load()
    if (manualTimer) clearTimeout(manualTimer)
    manualTimer = setTimeout(() => (manualMsg.value = ''), 5000)
  } catch (e) {
    // 422 (напр. BYN или неверная дата) — текст из detail.
    manualError.value = getErrorMessage(e, 'Не удалось добавить курс')
  } finally {
    manualSaving.value = false
  }
}

onMounted(load)

onUnmounted(() => {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (manualTimer) clearTimeout(manualTimer)
})
</script>

<template>
  <div>
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Курсы валют</h1>
        <p class="text-sm text-ink-muted mt-1">
          История курсов USD / EUR / RUB за последние 7 дней — НБ РБ и ручные значения.
        </p>
      </div>
      <button class="btn-primary shrink-0" :disabled="refreshing" @click="refreshRates">
        <span v-if="refreshing" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        <Icon v-else name="heroicons:arrow-path" class="w-4 h-4" />
        {{ refreshing ? 'Запрос…' : 'Обновить курсы НБ РБ' }}
      </button>
    </div>

    <div v-if="refreshError" class="badge-danger w-full justify-center py-2 mb-4">{{ refreshError }}</div>
    <div v-if="refreshMsg" class="badge-success w-full justify-center py-2 mb-4">
      <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ refreshMsg }}
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 6" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!sortedRates.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:banknotes" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>Курсов пока нет — обновите курсы НБ РБ или добавьте вручную</p>
    </div>

    <div v-else class="card overflow-hidden mb-8">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Валюта</th>
              <th class="px-4 py-3 font-medium">Дата</th>
              <th class="px-4 py-3 font-medium text-right">Курс, BYN</th>
              <th class="px-4 py-3 font-medium">Источник</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in sortedRates" :key="r.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 font-medium whitespace-nowrap">
                {{ CURRENCY_META[r.currency_code]?.label ?? r.currency_code }}
              </td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(r.fetched_at) }}</td>
              <td class="px-4 py-3 text-right font-mono whitespace-nowrap">
                {{ r.rate }}<span v-if="r.scale > 1" class="text-ink-faint text-xs ml-1.5">за {{ r.scale }} ед.</span>
              </td>
              <td class="px-4 py-3">
                <span :class="r.is_manual ? 'badge-warning' : 'badge-info'">{{ sourceLabel(r) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Ручной курс -->
    <div class="card p-6">
      <h2 class="font-semibold mb-4">Добавить курс вручную</h2>
      <p class="text-sm text-ink-muted mb-5">
        Ручной курс перекрывает курс НБ РБ на указанную дату для всех клиентов без фиксации.
      </p>

      <form class="flex flex-col sm:flex-row flex-wrap gap-4 sm:items-end" @submit.prevent="submitManual">
        <div class="sm:w-52">
          <label class="label" for="mc-currency">Валюта</label>
          <select id="mc-currency" v-model="manualForm.currency_code" class="input py-2.5">
            <option v-for="c in FIX_CURRENCIES" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="sm:w-44">
          <label class="label" for="mc-rate">Курс за 1 ед. (в BYN)</label>
          <input id="mc-rate" v-model="manualForm.rate" type="number" min="0" step="0.0001" class="input" placeholder="Напр. 3.27" required>
        </div>
        <div class="sm:w-44">
          <label class="label" for="mc-date">Дата</label>
          <input id="mc-date" v-model="manualForm.fetched_at" type="date" class="input py-2.5" required>
        </div>
        <button type="submit" class="btn-primary sm:ml-auto shrink-0" :disabled="!manualValid || manualSaving">
          <span v-if="manualSaving" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
          {{ manualSaving ? 'Добавление…' : 'Добавить' }}
        </button>
      </form>

      <div v-if="manualError" class="badge-danger w-full justify-center py-2 mt-5">{{ manualError }}</div>
      <div v-if="manualMsg" class="badge-success w-full justify-center py-2 mt-5">
        <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ manualMsg }}
      </div>
    </div>
  </div>
</template>
