<script setup lang="ts">
// 2FA менеджера (фича H, §16 п.22): setup → enable (QR + код) → recovery-коды; disable.
// Контракт: POST /auth/2fa/setup|enable|disable. Recovery-коды показываются ровно 1 раз.
import type { TwoFASetupOut } from '~/types/api'

definePageMeta({ layout: 'client', middleware: ['auth', 'role'], roles: ['MANAGER'] })
useHead({ title: 'Безопасность (2FA)' })

const auth = useAuth()
const { request } = useApi()

// Шаги: статус → qr (секрет+QR, подтверждение кодом) → codes (recovery-коды, 1 показ).
const step = ref<'status' | 'qr' | 'codes'>('status')
const setup = ref<TwoFASetupOut | null>(null)
const recoveryCodes = ref<string[]>([])
const code = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')
const copied = ref(false)

const totpEnabled = computed(() => auth.user?.totpEnabled ?? false)

/** Шаг 1: сгенерировать секрет + QR (НЕ сохраняет секрет на бэкенде). */
async function startSetup() {
  if (loading.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await request<{ data: TwoFASetupOut }>('/api/v1/auth/2fa/setup', { method: 'POST' })
    setup.value = res.data
    code.value = ''
    step.value = 'qr'
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось начать настройку 2FA')
  } finally {
    loading.value = false
  }
}

/** Шаг 2: подтвердить кодом из приложения → recovery-коды (показ 1 раз). */
async function onEnable() {
  if (loading.value || !setup.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await request<{ data: { recovery_codes: string[] } }>('/api/v1/auth/2fa/enable', {
      method: 'POST',
      body: { secret: setup.value.secret, code: code.value.trim() },
    })
    recoveryCodes.value = res.data.recovery_codes
    copied.value = false
    step.value = 'codes'
    await auth.fetchMe()
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось включить 2FA')
  } finally {
    loading.value = false
  }
}

function cancelSetup() {
  step.value = 'status'
  setup.value = null
  code.value = ''
  errorMsg.value = ''
}

/** Скопировать recovery-коды в буфер обмена. */
async function copyCodes() {
  try {
    await navigator.clipboard.writeText(recoveryCodes.value.join('\n'))
    copied.value = true
  } catch {
    copied.value = false
  }
}

/** Скачать recovery-коды файлом .txt. */
function downloadCodes() {
  const blob = new Blob([recoveryCodes.value.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'recovery-codes.txt'
  a.click()
  URL.revokeObjectURL(url)
}

/** Закрыть экран recovery-кодов → статус. */
function finish() {
  step.value = 'status'
  setup.value = null
  recoveryCodes.value = []
  copied.value = false
  code.value = ''
  errorMsg.value = ''
}

/** Отключить 2FA: код (TOTP/recovery) ИЛИ текущий пароль. */
async function onDisable() {
  if (loading.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await request('/api/v1/auth/2fa/disable', {
      method: 'POST',
      body: {
        code: code.value.trim() || undefined,
        password: password.value || undefined,
      },
    })
    code.value = ''
    password.value = ''
    await auth.fetchMe()
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось отключить 2FA')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <!-- Хлебные крошки: Профиль / Безопасность -->
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/profile" class="hover:text-primary">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Безопасность</span>
    </nav>

    <h1 class="text-2xl font-bold mb-6">Безопасность</h1>

    <div class="card p-5 max-w-2xl">
      <h3 class="font-semibold mb-1">Двухфакторная аутентификация (2FA)</h3>
      <p class="text-sm text-ink-muted mb-4">
        Дополнительный код из приложения-аутентификатора (Google Authenticator и совместимые)
        при каждом входе. Защищает кабинет, даже если пароль утёк.
      </p>

      <!-- Шаг qr: секрет + QR, подтверждение кодом из приложения -->
      <div v-if="step === 'qr' && setup" class="flex flex-col gap-4">
        <p class="text-sm text-ink">
          1. Отсканируйте QR-код приложением-аутентификатором или введите секрет вручную.
        </p>
        <div class="flex flex-col sm:flex-row items-center sm:items-start gap-4">
          <img :src="setup.qr_png_data_url" alt="QR-код для приложения-аутентификатора" class="w-44 h-44 shrink-0 rounded-card border border-border bg-white p-2">
          <div class="min-w-0 w-full">
            <label class="label">Секрет для ручного ввода</label>
            <code class="block px-3 py-2 rounded-card bg-canvas border border-border font-mono text-sm break-all select-all">{{ setup.secret }}</code>
            <p class="text-xs text-ink-faint mt-1.5">
              Приложение покажет 6-значный код, обновляющийся каждые 30 секунд.
            </p>
          </div>
        </div>

        <form class="flex flex-col gap-4" @submit.prevent="onEnable">
          <div>
            <label class="label" for="twofa-enable-code">Код из приложения</label>
            <input
              id="twofa-enable-code"
              v-model="code"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              required
              minlength="6"
              maxlength="10"
              class="input font-mono tracking-widest text-center"
              placeholder="000000"
            >
          </div>

          <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>

          <div class="flex items-center gap-3">
            <button type="submit" class="btn-primary" :disabled="loading || code.trim().length < 6">
              <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
              {{ loading ? 'Проверка...' : 'Включить 2FA' }}
            </button>
            <button type="button" class="btn-ghost" :disabled="loading" @click="cancelSetup">Отменить</button>
          </div>
        </form>
      </div>

      <!-- Шаг codes: recovery-коды, показ ровно 1 раз -->
      <div v-else-if="step === 'codes'">
        <div class="badge-warning mb-4">
          <Icon name="heroicons:exclamation-triangle" class="w-4 h-4" />
          Recovery-коды показываются только один раз
        </div>
        <p class="text-sm text-ink-muted mb-4">
          Сохраните коды в надёжном месте: каждый можно использовать однократно, если
          приложение-аутентификатор недоступно.
        </p>
        <ol class="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-5">
          <li v-for="(c, i) in recoveryCodes" :key="i" class="px-3 py-2 rounded-card bg-canvas border border-border font-mono text-sm select-all">{{ i + 1 }}. {{ c }}</li>
        </ol>
        <div class="flex flex-wrap items-center gap-3">
          <button class="btn-secondary" @click="copyCodes">
            <Icon :name="copied ? 'heroicons:check' : 'heroicons:clipboard-document'" class="w-4 h-4" />
            {{ copied ? 'Скопировано' : 'Скопировать все' }}
          </button>
          <button class="btn-secondary" @click="downloadCodes">
            <Icon name="heroicons:arrow-down-tray" class="w-4 h-4" />
            Скачать .txt
          </button>
          <button class="btn-primary ml-auto" @click="finish">Готово</button>
        </div>
      </div>

      <!-- Статус: включена/выключена -->
      <template v-else>
        <div class="flex items-center gap-2 mb-4">
          <span v-if="totpEnabled" class="badge-success">
            <Icon name="heroicons:shield-check" class="w-4 h-4" />
            Защита включена
          </span>
          <span v-else class="badge-warning">
            <Icon name="heroicons:shield-exclamation" class="w-4 h-4" />
            Защита выключена
          </span>
        </div>

        <div v-if="!totpEnabled">
          <button class="btn-primary" :disabled="loading" @click="startSetup">
            <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
            {{ loading ? 'Подготовка...' : 'Включить' }}
          </button>
          <div v-if="errorMsg" class="badge-danger mt-4">{{ errorMsg }}</div>
        </div>

        <form v-else class="flex flex-col gap-4" @submit.prevent="onDisable">
          <p class="text-sm text-ink-muted">
            Для отключения подтвердите личность: введите код из приложения или текущий пароль.
          </p>
          <div>
            <label class="label" for="twofa-disable-code">Код из приложения (или recovery-код)</label>
            <input
              id="twofa-disable-code"
              v-model="code"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              minlength="6"
              maxlength="10"
              class="input font-mono tracking-widest"
              placeholder="000000"
            >
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-ink-faint">или</span>
            <div class="flex-1">
              <label class="label" for="twofa-disable-password">Текущий пароль</label>
              <input id="twofa-disable-password" v-model="password" type="password" autocomplete="current-password" class="input" placeholder="••••••••" >
            </div>
          </div>

          <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>

          <div>
            <button type="submit" class="btn-outline" :disabled="loading">
              <span v-if="loading" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
              {{ loading ? 'Отключение...' : 'Отключить 2FA' }}
            </button>
          </div>
        </form>
      </template>
    </div>
  </div>
</template>
