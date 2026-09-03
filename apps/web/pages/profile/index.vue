<script setup lang="ts">
// Профиль: личные данные, безопасность, Telegram, уведомления, согласие на ПДн.
// Валюта отображения — только BYN, определяется менеджером (клиент не меняет).
// Telegram-код связки: Этап 12, §16 п.27. См. SITEMAP.md §5.
import type { TelegramLinkCode } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Профиль' })

const auth = useAuth()
const { request } = useApi()

// --- Оформление: тёмная/светлая тема (useTheme — обёртка над @nuxtjs/color-mode) ---
const { mode: themeMode, toggle: toggleTheme } = useTheme()

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
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Телефон</span>
          <span class="font-medium">{{ auth.user?.phone || '—' }}</span>
        </div>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Email</span>
          <span class="font-medium">{{ auth.user?.email || '—' }}</span>
        </div>
        <div class="flex justify-between items-center text-sm py-1.5">
          <span class="text-ink-muted">Валюта отображения</span>
          <span class="font-medium">BYN</span>
        </div>
        <p class="text-xs text-ink-faint mt-3">
          Для изменения данных обратитесь к менеджеру. Валюта определяется менеджером.
        </p>
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

      <!-- Telegram Mini App: код связки (только CLIENT, §16 п.27). -->
      <div v-if="auth.isClient" class="card p-5 h-full">
        <h3 class="font-semibold mb-3">Telegram</h3>
        <p class="text-sm text-ink-muted mb-4">
          Свяжите аккаунт, чтобы открывать каталог и оформлять заявки прямо в Telegram.
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
            Действует 10 минут. Откройте Mini App в Telegram и введите код.
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
