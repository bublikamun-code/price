<script setup lang="ts">
import type { TwoFASetupOut } from '~/types/api'

definePageMeta({ layout: 'client', middleware: ['auth', 'role'], roles: ['MANAGER'] })
useHead({ title: 'Безопасность (2FA)' })

const auth = useAuth()
const { request } = useApi()

const step = ref<'status' | 'qr' | 'codes'>('status')
const setup = ref<TwoFASetupOut | null>(null)
const recoveryCodes = ref<string[]>([])
const code = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')
const copied = ref(false)

const totpEnabled = computed(() => auth.user?.totpEnabled ?? false)

async function startSetup() {
  if (loading.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await request<{ data: TwoFASetupOut }>('/api/v1/auth/2fa/setup', {
      method: 'POST',
    })
    setup.value = response.data
    code.value = ''
    step.value = 'qr'
  } catch (error) {
    errorMsg.value = getErrorMessage(error, 'Не удалось начать настройку 2FA')
  } finally {
    loading.value = false
  }
}

async function onEnable() {
  if (loading.value || !setup.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await request<{ data: { recovery_codes: string[] } }>('/api/v1/auth/2fa/enable', {
      method: 'POST',
      body: { secret: setup.value.secret, code: code.value.trim() },
    })
    recoveryCodes.value = response.data.recovery_codes
    copied.value = false
    step.value = 'codes'
    await auth.fetchMe()
  } catch (error) {
    errorMsg.value = getErrorMessage(error, 'Не удалось включить 2FA')
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

async function copyCodes() {
  try {
    await navigator.clipboard.writeText(recoveryCodes.value.join('\n'))
    copied.value = true
  } catch {
    copied.value = false
  }
}

function downloadCodes() {
  const blob = new Blob([recoveryCodes.value.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'recovery-codes.txt'
  anchor.click()
  URL.revokeObjectURL(url)
}

function finish() {
  step.value = 'status'
  setup.value = null
  recoveryCodes.value = []
  copied.value = false
  code.value = ''
  errorMsg.value = ''
}

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
  } catch (error) {
    errorMsg.value = getErrorMessage(error, 'Не удалось отключить 2FA')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl">
    <nav class="mb-6 flex items-center gap-2 text-sm text-ink-muted" aria-label="Хлебные крошки">
      <NuxtLink to="/profile" class="hover:text-action">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-4" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Безопасность</span>
    </nav>

    <PageHeading
      eyebrow="Защита учётной записи"
      title="Двухфакторная аутентификация"
      description="Код из приложения-аутентификатора запрашивается при каждом входе вместе с паролем."
    />

    <div v-if="step === 'qr' && setup" class="py-6">
      <section class="grid border-b border-border pb-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="setup-heading">
        <h2 id="setup-heading" class="text-sm font-bold text-ink">Шаг 1. Подключение</h2>
        <div>
          <p class="font-semibold text-ink">Отсканируйте QR-код или введите секрет вручную.</p>
          <div class="mt-5 grid gap-5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:items-start">
            <img
              :src="setup.qr_png_data_url"
              alt="QR-код для приложения-аутентификатора"
              class="size-44 border border-border bg-surface p-2"
              width="176"
              height="176"
            >
            <div class="min-w-0">
              <p class="label">Секрет для ручного ввода</p>
              <code class="block select-all break-all border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-ink">{{ setup.secret }}</code>
              <p class="mt-2 text-sm text-ink-muted">Приложение покажет шестизначный код, который обновляется каждые 30 секунд.</p>
            </div>
          </div>
        </div>
      </section>

      <form class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" @submit.prevent="onEnable">
        <h2 class="text-sm font-bold text-ink">Шаг 2. Подтверждение</h2>
        <div class="max-w-sm">
          <label for="twofa-enable-code" class="label">Код из приложения</label>
          <input
            id="twofa-enable-code"
            v-model="code"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            minlength="6"
            maxlength="10"
            class="input text-center font-mono tracking-[0.2em]"
            placeholder="000000"
            :aria-invalid="Boolean(errorMsg)"
            :aria-describedby="errorMsg ? 'twofa-enable-error' : undefined"
          >
          <p v-if="errorMsg" id="twofa-enable-error" class="mt-2 text-sm text-danger-text" role="alert">{{ errorMsg }}</p>
          <div class="mt-5 flex flex-wrap gap-3">
            <button type="submit" class="btn-primary" :disabled="loading || code.trim().length < 6">
              <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
              {{ loading ? 'Проверяем' : 'Включить 2FA' }}
            </button>
            <button type="button" class="btn-outline" :disabled="loading" @click="cancelSetup">Отменить</button>
          </div>
        </div>
      </form>
    </div>

    <section v-else-if="step === 'codes'" class="py-6" aria-labelledby="recovery-heading">
      <div class="grid gap-2 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8">
        <h2 id="recovery-heading" class="text-sm font-bold text-ink">Коды восстановления</h2>
        <div>
          <div class="border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning-text" role="status">
            Коды показываются один раз. Сохраните их до закрытия этого шага.
          </div>
          <p class="mt-4 text-sm text-ink-muted">Каждый код можно использовать однократно, если приложение-аутентификатор недоступно.</p>
          <ol class="mt-5 grid border-y border-border sm:grid-cols-2 sm:divide-x sm:divide-border">
            <li v-for="(recoveryCode, index) in recoveryCodes" :key="index" class="grid grid-cols-[2rem_minmax(0,1fr)] border-b border-border px-3 py-2 font-mono text-sm last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
              <span class="text-ink-muted">{{ index + 1 }}.</span>
              <span class="select-all text-ink">{{ recoveryCode }}</span>
            </li>
          </ol>
          <div class="mt-5 flex flex-wrap gap-3">
            <button type="button" class="btn-outline" @click="copyCodes">
              <Icon :name="copied ? 'heroicons:check' : 'heroicons:clipboard-document'" class="size-4" aria-hidden="true" />
              {{ copied ? 'Скопировано' : 'Скопировать' }}
            </button>
            <button type="button" class="btn-outline" @click="downloadCodes">Скачать .txt</button>
            <button type="button" class="btn-primary sm:ml-auto" @click="finish">Готово</button>
          </div>
        </div>
      </div>
    </section>

    <section v-else class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="status-heading">
      <h2 id="status-heading" class="text-sm font-bold text-ink">Состояние</h2>
      <div>
        <div class="flex items-center gap-2">
          <span v-if="totpEnabled" class="badge-success">Включена</span>
          <span v-else class="badge-warning">Выключена</span>
        </div>

        <div v-if="!totpEnabled" class="mt-5">
          <p class="max-w-xl text-sm text-ink-muted">После подтверждения будут выданы коды восстановления для входа без приложения.</p>
          <button type="button" class="btn-primary mt-5" :disabled="loading" @click="startSetup">
            <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
            {{ loading ? 'Готовим' : 'Включить 2FA' }}
          </button>
          <p v-if="errorMsg" class="mt-3 text-sm text-danger-text" role="alert">{{ errorMsg }}</p>
        </div>

        <form v-else class="mt-5 max-w-xl space-y-4" @submit.prevent="onDisable">
          <p class="text-sm text-ink-muted">Подтвердите отключение кодом из приложения, recovery-кодом или текущим паролем.</p>
          <div>
            <label for="twofa-disable-code" class="label">Код или recovery-код</label>
            <input
              id="twofa-disable-code"
              v-model="code"
              type="text"
              autocomplete="one-time-code"
              minlength="6"
              maxlength="10"
              class="input font-mono"
              placeholder="Код"
            >
          </div>
          <div>
            <label for="twofa-disable-password" class="label">Текущий пароль</label>
            <input
              id="twofa-disable-password"
              v-model="password"
              type="password"
              autocomplete="current-password"
              class="input"
              placeholder="Пароль"
            >
          </div>
          <p v-if="errorMsg" class="text-sm text-danger-text" role="alert">{{ errorMsg }}</p>
          <button type="submit" class="btn-outline text-danger-text" :disabled="loading">
            <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
            {{ loading ? 'Отключаем' : 'Отключить 2FA' }}
          </button>
        </form>
      </div>
    </section>
  </div>
</template>
