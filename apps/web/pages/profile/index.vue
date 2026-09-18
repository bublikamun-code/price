<script setup lang="ts">
// Профиль: личные данные, мои условия, валюта, безопасность, Telegram,
// уведомления, согласие на ПДн. См. SITEMAP.md §6 /profile, канон §8
// (display_currency — выбор клиента, PATCH /auth/me).
import type { TelegramLinkCode } from '~/types/api'
import { getErrorMessage } from '~/utils/errors'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Профиль' })

const auth = useAuth()
const { request } = useApi()

// --- Редактирование телефона и email (self-service) ---
// TODO: бэкенд PATCH /auth/me пока не принимает phone/email.
// Когда эндпоинт будет расширен — заменить saveProfile на реальный вызов updateMe.
const editPhone = ref('')
const editEmail = ref('')
const profileSaving = ref(false)
const profileSuccess = ref(false)
const profileError = ref('')

const phoneChanged = computed(() => editPhone.value.trim() !== (auth.user?.phone || ''))
const emailChanged = computed(() => editEmail.value.trim() !== (auth.user?.email || ''))

// Инициализация значений из auth.user.
onMounted(() => {
  editPhone.value = auth.user?.phone || ''
  editEmail.value = auth.user?.email || ''
})

async function saveProfile() {
  if (profileSaving.value) return
  profileSaving.value = true
  profileSuccess.value = false
  profileError.value = ''
  try {
    // TODO: когда PATCH /auth/me начнёт принимать phone/email, заменить на:
    //   await auth.updateMe({ phone: editPhone.value.trim(), email: editEmail.value.trim() })
    // Пока бэкенд не поддерживает — показываем информативное сообщение.
    await new Promise((_, reject) =>
      setTimeout(() => reject(new Error(
        'Сохранение телефона и email через портал пока не поддерживается. Обратитесь к менеджеру для изменения контактных данных.',
      )), 300),
    )
  } catch (e) {
    profileError.value = getErrorMessage(e, 'Не удалось сохранить данные', { withMessage: true })
  } finally {
    profileSaving.value = false
  }
}

// --- Оформление: тёмная/светлая тема (useTheme — обёртка над @nuxtjs/color-mode) ---
const { mode: themeMode, toggle: toggleTheme } = useTheme()

// --- Валюта отображения (§8 — выбор клиента) ---
const CURRENCIES = ['BYN', 'USD', 'EUR', 'RUB'] as const
const currencySaving = ref(false)
const currencySaved = ref(false)
const currencyError = ref('')

async function setDisplayCurrency(code: string) {
  if (currencySaving.value || code === auth.user?.displayCurrency) return
  currencySaving.value = true
  currencySaved.value = false
  currencyError.value = ''
  try {
    await auth.updateMe({ display_currency: code })
    currencySaved.value = true
    setTimeout(() => { currencySaved.value = false }, 2000)
  } catch (e) {
    currencyError.value = getErrorMessage(e, 'Не удалось изменить валюту')
  } finally {
    currencySaving.value = false
  }
}

// --- Мои условия (SITEMAP §6): скидки по брендам + фикс. курс договора ---
interface MyTerms {
  discounts: { brand_id: string; brand_name: string; discount_percent: number }[]
  fixed_rate: { currency: string; rate: number; source: string | null; fetched_at: string | null } | null
}
const { data: myTerms, error: termsError } = await useAsyncData(
  'my-terms',
  () => request<MyTerms>('/api/v1/auth/my-terms'),
  { server: false },
)

// --- Telegram Mini App: код связки (§16 п.27, SITEMAP §8). Только CLIENT. ---
const tgCode = ref('')
const tgGenerating = ref(false)
const tgError = ref('')

async function generateLinkCode() {
  if (tgGenerating.value) return
  tgGenerating.value = true
  tgError.value = ''
  try {
    const res = await request<TelegramLinkCode>('/api/v1/auth/telegram/link-code', { method: 'POST' })
    tgCode.value = res.code
  } catch (e) {
    tgCode.value = ''
    tgError.value = getErrorMessage(e, 'Не удалось сгенерировать код связки')
  } finally {
    tgGenerating.value = false
  }
}
</script>

<template>
  <div>
    <!-- Заголовок -->
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Профиль</h1>
    </div>

    <div class="grid gap-6 lg:grid-cols-2 items-stretch">
      <!-- Личные данные (readonly) -->
      <div class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Личные данные</h3>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">ФИО</span>
          <span class="font-medium">{{ auth.user?.name || '—' }}</span>
        </div>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Компания</span>
          <span class="font-medium">{{ auth.user?.company || '—' }}</span>
        </div>
        <div class="mt-4 space-y-3">
          <div>
            <label class="label" for="profile-phone">Телефон</label>
            <input
              id="profile-phone"
              v-model="editPhone"
              type="tel"
              class="input"
              :placeholder="auth.user?.phone || '+375 29 000-00-00'"
            >
          </div>
          <div>
            <label class="label" for="profile-email">Email</label>
            <input
              id="profile-email"
              v-model="editEmail"
              type="email"
              class="input"
              :placeholder="auth.user?.email || 'you@company.by'"
            >
          </div>
          <button
            type="button"
            class="btn-accent px-5 py-2 text-sm"
            :disabled="profileSaving || (!phoneChanged && !emailChanged)"
            @click="saveProfile"
          >
            {{ profileSaving ? 'Сохранение…' : 'Сохранить изменения' }}
          </button>
          <div v-if="profileSuccess" class="badge-success">Данные обновлены</div>
          <div v-if="profileError" class="badge-danger">{{ profileError }}</div>
        </div>
        <div class="flex justify-between items-center text-sm py-1.5">
          <span class="text-ink-muted">Валюта отображения</span>
          <span class="flex items-center gap-1.5">
            <button
              v-for="c in CURRENCIES"
              :key="c"
              type="button"
              class="px-2.5 py-1 rounded-pill text-xs font-semibold border transition-colors duration-150"
              :class="auth.user?.displayCurrency === c
                ? 'bg-primary text-white border-primary'
                : 'border-border text-ink-muted hover:border-primary/50 hover:text-primary'"
              :disabled="currencySaving"
              :aria-pressed="auth.user?.displayCurrency === c"
              @click="setDisplayCurrency(c)"
            >
              {{ c }}
            </button>
          </span>
        </div>
        <p v-if="currencySaved" class="text-xs text-success mt-2">Валюта сохранена</p>
        <p v-else-if="currencyError" class="text-xs text-danger mt-2">{{ currencyError }}</p>
        <p class="text-xs text-ink-faint mt-3">
          Телефон и email можно изменить самостоятельно. Для изменения ФИО и компании обратитесь к менеджеру. Курсы конвертации — по НБ РБ или фикс. курсу договора.
        </p>
      </div>

      <!-- Мои условия (SITEMAP §6): персональные скидки по брендам + фикс. курс -->
      <div class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Мои условия</h3>
        <div v-if="termsError" class="text-sm text-ink-muted">Не удалось загрузить условия</div>
        <template v-else>
          <div v-for="d in myTerms?.discounts ?? []" :key="d.brand_id" class="flex justify-between text-sm py-1.5">
            <span class="text-ink-muted">{{ d.brand_name }}</span>
            <span class="font-medium">{{ d.discount_percent > 0 ? `−${d.discount_percent}%` : 'базовая цена' }}</span>
          </div>
          <div v-if="!myTerms?.discounts?.length" class="text-sm text-ink-muted py-1.5">
            Персональные скидки не заведены — цены по базовому прайсу.
          </div>
          <div v-if="myTerms?.fixed_rate" class="mt-3 pt-3 border-t border-border">
            <div class="flex justify-between text-sm py-1">
              <span class="text-ink-muted">Фикс. курс договора</span>
              <span class="font-medium">1 {{ myTerms.fixed_rate.currency }} = {{ myTerms.fixed_rate.rate }} BYN</span>
            </div>
            <p v-if="myTerms.fixed_rate.source" class="text-xs text-ink-faint mt-1">Источник: {{ myTerms.fixed_rate.source }}</p>
          </div>
        </template>
      </div>

      <!-- Безопасность (2FA — менеджер; сессии — все роли). Фичи H/I, §16 п.22 -->
      <div class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Безопасность</h3>
        <div class="flex flex-col gap-1">
          <NuxtLink
            v-if="auth.isManager"
            to="/profile/security"
            class="flex items-center gap-3 px-3 py-2.5 -mx-3 rounded-card hover:bg-canvas/60 transition-colors"
          >
            <Icon name="heroicons:shield-check" class="w-5 h-5 shrink-0 text-primary" />
            <span class="flex-1 text-sm font-medium">Безопасность (2FA)</span>
            <span :class="auth.user?.totpEnabled ? 'text-xs text-success font-medium' : 'text-xs text-ink-faint'">
              {{ auth.user?.totpEnabled ? 'включена' : 'выключена' }}
            </span>
            <Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint" />
          </NuxtLink>
          <NuxtLink
            to="/profile/sessions"
            class="flex items-center gap-3 px-3 py-2.5 -mx-3 rounded-card hover:bg-canvas/60 transition-colors"
          >
            <Icon name="heroicons:device-phone-mobile" class="w-5 h-5 shrink-0 text-primary" />
            <span class="flex-1 text-sm font-medium">Активные сессии</span>
            <Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint" />
          </NuxtLink>
        </div>
        <p class="text-xs text-ink-faint mt-3">
          Завершайте сессии на чужих устройствах{{ auth.isManager ? ' и управляйте двухфакторной аутентификацией' : '' }}.
        </p>
      </div>

      <!-- Telegram: код связки для бота @svetvdome_bot (только CLIENT, §16 п.27). -->
      <div v-if="auth.isClient" class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Telegram</h3>
        <p class="text-sm text-ink-muted mb-4">
          Свяжите аккаунт с ботом
          <a
            href="https://t.me/svetvdome_bot"
            target="_blank"
            rel="noopener"
            class="text-primary hover:underline"
          >@svetvdome_bot</a>,
          чтобы получать уведомления об изменении цен и статусах заявок прямо в Telegram.
        </p>

        <button
          class="btn-primary"
          :disabled="tgGenerating"
          @click="generateLinkCode"
        >
          <span v-if="tgGenerating" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <Icon v-else name="heroicons:paper-airplane" class="w-4 h-4" />
          {{ tgGenerating ? 'Генерация…' : 'Сгенерировать код связки' }}
        </button>

        <div v-if="tgCode" class="mt-4 text-center bg-primary-soft/40 border border-primary/20 rounded-card p-4">
          <div class="text-3xl font-display font-bold tracking-[0.3em] text-primary">{{ tgCode }}</div>
          <p class="text-xs text-ink-faint mt-2">
            Действует 10 минут. Откройте бота @svetvdome_bot в Telegram и отправьте
            ему команду /start с этим кодом.
          </p>
        </div>

        <div v-if="tgError" class="badge-danger w-full justify-center py-2 mt-3">{{ tgError }}</div>
      </div>

      <!-- Уведомления -->
      <NuxtLink to="/profile/notifications" class="card p-5 h-full group hover:border-primary/50 transition-colors">
        <div class="flex items-start gap-3">
          <Icon name="heroicons:bell-alert" class="w-5 h-5 shrink-0 text-primary mt-0.5" />
          <div class="flex-1">
            <h3 class="font-semibold mb-1 flex items-center gap-2">
              Уведомления
              <Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint group-hover:text-primary transition-colors" />
            </h3>
            <p class="text-sm text-ink-muted">
              Настройте, о каких событиях сообщать: изменения цен в корзине и избранном, статусы заявок.
            </p>
          </div>
        </div>
      </NuxtLink>

      <!-- Оформление: тёмная/светлая тема -->
      <div class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Оформление</h3>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <Icon name="heroicons:moon" class="w-5 h-5 text-ink-muted" />
            <span class="text-sm font-medium">Тёмная тема</span>
          </div>
          <button
            type="button"
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            :class="themeMode === 'dark' ? 'bg-primary' : 'bg-border'"
            @click="toggleTheme"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="themeMode === 'dark' ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
        </div>
        <p class="text-xs text-ink-faint mt-3">Переключатель сохраняется в этом браузере.</p>
      </div>

      <!-- Согласие и данные (на всю ширину) -->
      <div class="card p-5 h-full lg:col-span-2">
        <h3 class="font-semibold mb-3">Согласие и данные</h3>
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <span class="text-sm text-ink-muted">Согласие на обработку персональных данных:</span>
            <span v-if="auth.user?.consent_accepted" class="badge-success">Принято</span>
            <template v-else>
              <span class="badge-warning">Не оформлено</span>
            </template>
          </div>
          <p v-if="!auth.user?.consent_accepted" class="text-xs text-ink-faint">
            Отозвать согласие можно через менеджера.
          </p>
        </div>
      </div>

      <!-- Файлы и документы (на всю ширину) -->
      <NuxtLink to="/files" class="card p-5 h-full lg:col-span-2 group hover:border-primary/50 transition-colors">
        <div class="flex items-start gap-3">
          <Icon name="heroicons:folder-open" class="w-5 h-5 shrink-0 text-primary mt-0.5" />
          <div class="flex-1">
            <h3 class="font-semibold mb-1 flex items-center gap-2">
              Файлы и документы
              <Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint group-hover:text-primary transition-colors" />
            </h3>
            <p class="text-sm text-ink-muted">
              Прайс-листы, сертификаты и другие документы от вашего менеджера — в одном месте.
            </p>
          </div>
        </div>
      </NuxtLink>

    </div>
  </div>
</template>
