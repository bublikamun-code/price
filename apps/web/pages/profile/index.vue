<script setup lang="ts">
import type { TelegramLinkCode } from '~/types/api'
import { getErrorMessage } from '~/utils/errors'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Профиль' })

const auth = useAuth()
const { request } = useApi()

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
    window.setTimeout(() => {
      currencySaved.value = false
    }, 2500)
  } catch (error) {
    currencyError.value = getErrorMessage(error, 'Не удалось изменить валюту')
  } finally {
    currencySaving.value = false
  }
}

function onCurrencyChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  void setDisplayCurrency(value)
}

interface MyTerms {
  discounts: { brand_id: string; brand_name: string; discount_percent: number }[]
  fixed_rate: { currency: string; rate: number; source: string | null; fetched_at: string | null } | null
}
const { data: myTerms, error: termsError } = await useAsyncData(
  'my-terms',
  () => request<MyTerms>('/api/v1/auth/my-terms'),
  { server: false },
)

const tgCode = ref('')
const tgGenerating = ref(false)
const tgError = ref('')

async function generateLinkCode() {
  if (tgGenerating.value) return
  tgGenerating.value = true
  tgError.value = ''
  try {
    const response = await request<TelegramLinkCode>('/api/v1/auth/telegram/link-code', {
      method: 'POST',
    })
    tgCode.value = response.code
  } catch (error) {
    tgCode.value = ''
    tgError.value = getErrorMessage(error, 'Не удалось сгенерировать код связки')
  } finally {
    tgGenerating.value = false
  }
}

const roleLabel = computed(() => {
  if (auth.isManager) return 'Менеджер'
  if (auth.isClient) return 'Клиент'
  return auth.user?.role || '—'
})
</script>

<template>
  <div class="mx-auto max-w-5xl">
    <PageHeading
      eyebrow="Учётная запись"
      title="Профиль"
      description="Личные данные, коммерческие условия и параметры рабочего кабинета в одной записи."
    />

    <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="identity-heading">
      <h2 id="identity-heading" class="text-sm font-bold text-ink">Личные данные</h2>
      <dl class="divide-y divide-border">
        <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
          <dt class="text-sm text-ink-muted">ФИО</dt>
          <dd class="font-semibold text-ink">{{ auth.user?.name || '—' }}</dd>
        </div>
        <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
          <dt class="text-sm text-ink-muted">Email</dt>
          <dd class="break-all font-mono text-sm text-ink">{{ auth.user?.email || '—' }}</dd>
        </div>
        <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
          <dt class="text-sm text-ink-muted">Телефон</dt>
          <dd class="font-mono text-sm text-ink">{{ auth.user?.phone || 'Не указан' }}</dd>
        </div>
        <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
          <dt class="text-sm text-ink-muted">Роль</dt>
          <dd class="font-semibold text-ink">{{ roleLabel }}</dd>
        </div>
      </dl>
      <p class="mt-4 text-sm text-ink-muted md:col-start-2">
        Контактные данные и ФИО изменяет менеджер: в клиентском кабинете соответствующего запроса пока нет.
      </p>
    </section>

    <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="commercial-heading">
      <h2 id="commercial-heading" class="text-sm font-bold text-ink">Коммерческие условия</h2>
      <div>
        <div v-if="termsError" class="border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger-text" role="alert">
          Не удалось загрузить коммерческие условия.
        </div>
        <dl v-else class="divide-y divide-border">
          <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Скидки по брендам</dt>
            <dd class="space-y-2 text-sm">
              <div v-for="discount in myTerms?.discounts ?? []" :key="discount.brand_id" class="grid gap-1 sm:grid-cols-[minmax(0,1fr)_6rem] sm:gap-4">
                <span class="font-semibold text-ink">{{ discount.brand_name }}</span>
                <span class="font-mono text-ink sm:text-right">
                  {{ discount.discount_percent > 0 ? `−${discount.discount_percent}%` : 'базовая цена' }}
                </span>
              </div>
              <p v-if="!myTerms?.discounts?.length" class="text-ink-muted">
                Персональные скидки не заведены — действует базовый прайс.
              </p>
            </dd>
          </div>
          <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Курс договора</dt>
            <dd v-if="myTerms?.fixed_rate" class="space-y-1">
              <p class="font-mono text-sm font-semibold text-ink">
                1 {{ myTerms.fixed_rate.currency }} = {{ myTerms.fixed_rate.rate }} BYN
              </p>
              <p v-if="myTerms.fixed_rate.source" class="text-xs text-ink-muted">Источник: {{ myTerms.fixed_rate.source }}</p>
            </dd>
            <dd v-else class="text-sm text-ink-muted">Фиксированный курс не задан.</dd>
          </div>
          <div v-if="auth.isClient" class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Организация</dt>
            <dd>
              <NuxtLink to="/profile/organization" class="font-semibold text-action underline underline-offset-4 hover:text-action-hover">
                Проверить организацию и доступы
              </NuxtLink>
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <section id="profile-currency" class="grid scroll-mt-24 border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="currency-heading">
      <h2 id="currency-heading" class="text-sm font-bold text-ink">Валюта</h2>
      <div class="max-w-sm">
        <label for="profile-currency" class="label">Валюта отображения прайсов</label>
        <select
          id="profile-currency"
          class="input"
          :value="auth.user?.displayCurrency"
          :disabled="currencySaving"
          @change="onCurrencyChange"
        >
          <option v-for="currency in CURRENCIES" :key="currency" :value="currency">{{ currency }}</option>
        </select>
        <p class="mt-2 text-sm text-ink-muted">Изменение сохраняется через PATCH /auth/me.</p>
        <p v-if="currencySaved" class="mt-2 text-sm font-semibold text-success-text" role="status">Валюта сохранена.</p>
        <p v-if="currencyError" class="mt-2 text-sm text-danger-text" role="alert">{{ currencyError }}</p>
      </div>
    </section>

    <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="communications-heading">
      <h2 id="communications-heading" class="text-sm font-bold text-ink">Уведомления</h2>
      <div class="space-y-5">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p class="font-semibold text-ink">Дайджест изменения цен</p>
            <p class="mt-1 text-sm text-ink-muted">Источники отслеживания: заявка, избранное и заказы.</p>
          </div>
          <NuxtLink to="/profile/notifications" class="btn-outline shrink-0">Настроить</NuxtLink>
        </div>

        <div v-if="auth.isClient" class="border-t border-border pt-5">
          <p class="font-semibold text-ink">Telegram</p>
          <p class="mt-1 max-w-2xl text-sm text-ink-muted">
            Свяжите кабинет с
            <a href="https://t.me/svetvdome_bot" target="_blank" rel="noopener" class="font-semibold text-action underline underline-offset-4">@svetvdome_bot</a>,
            чтобы получать сообщения об изменении цен и статусах заявок.
          </p>
          <button type="button" class="btn-outline mt-4" :disabled="tgGenerating" @click="generateLinkCode">
            <span v-if="tgGenerating" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
            {{ tgGenerating ? 'Создаём код' : 'Создать код связки' }}
          </button>
          <div v-if="tgCode" class="mt-4 border border-border bg-surface-2 p-4" role="status">
            <p class="font-mono text-2xl font-semibold tracking-[0.24em] text-ink">{{ tgCode }}</p>
            <p class="mt-2 text-sm text-ink-muted">Код действует 10 минут. Отправьте боту команду /start с этим кодом.</p>
          </div>
          <p v-if="tgError" class="mt-3 text-sm text-danger-text" role="alert">{{ tgError }}</p>
        </div>
      </div>
    </section>

    <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="security-heading">
      <h2 id="security-heading" class="text-sm font-bold text-ink">Безопасность</h2>
      <div class="divide-y divide-border">
        <div class="flex items-center gap-4 py-3 first:pt-0">
          <div class="min-w-0 flex-1">
            <p class="font-semibold text-ink">Активные сессии</p>
            <p class="mt-1 text-sm text-ink-muted">Проверьте устройства, с которых выполнен вход.</p>
          </div>
          <NuxtLink to="/profile/sessions" class="btn-outline shrink-0">Проверить</NuxtLink>
        </div>
        <div v-if="auth.isManager" class="flex items-center gap-4 py-3 last:pb-0">
          <div class="min-w-0 flex-1">
            <p class="font-semibold text-ink">Двухфакторная аутентификация</p>
            <p class="mt-1 text-sm text-ink-muted">
              {{ auth.user?.totpEnabled ? 'Включена для этой учётной записи.' : 'Не включена для этой учётной записи.' }}
            </p>
          </div>
          <NuxtLink to="/profile/security" class="btn-outline shrink-0">Настроить</NuxtLink>
        </div>
      </div>
    </section>

    <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="privacy-heading">
      <h2 id="privacy-heading" class="text-sm font-bold text-ink">Данные и доступ</h2>
      <div class="space-y-4">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p class="font-semibold text-ink">Согласие на обработку персональных данных</p>
            <p class="mt-1 text-sm text-ink-muted">
              {{ auth.user?.consent_accepted ? 'Согласие зафиксировано.' : 'Согласие ещё не оформлено.' }}
            </p>
          </div>
          <span v-if="auth.user?.consent_accepted" class="badge-success">Принято</span>
          <NuxtLink v-else to="/consent" class="btn-outline shrink-0">Оформить</NuxtLink>
        </div>
        <div class="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p class="font-semibold text-ink">Завершение сессии</p>
            <p class="mt-1 text-sm text-ink-muted">Выйдите из кабинета на этом устройстве.</p>
          </div>
          <button type="button" class="btn-outline text-danger-text shrink-0" @click="auth.logout()">Выйти</button>
        </div>
      </div>
    </section>
  </div>
</template>
