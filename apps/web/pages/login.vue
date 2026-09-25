<script setup lang="ts">
definePageMeta({ layout: 'auth' })
useHead({ title: 'Вход' })

type FormStep = 'credentials' | 'two-factor' | 'forgot-password'

const auth = useAuth()
const route = useRoute()
const { request } = useApi()

const formStep = ref<FormStep>('credentials')
const showContactModal = ref(false)
const email = ref('')
const password = ref('')
const remember = ref(true)
const loading = ref(false)
const errorMsg = ref('')
const ticket = ref('')
const code = ref('')
const codeInputId = 'twofa-code'

const forgotEmail = ref('')
const forgotLoading = ref(false)
const forgotSent = ref(false)
const forgotError = ref('')

function getPostLoginPath(): string {
  const fallback = auth.isManager ? '/manager' : '/dashboard'
  return getSafeRedirectPath(route.query.redirect, fallback)
}

watch(formStep, (step) => {
  errorMsg.value = ''
  if (step === 'two-factor') nextTick(() => document.getElementById(codeInputId)?.focus())
})

function openForgotPassword() {
  forgotSent.value = false
  forgotEmail.value = ''
  forgotError.value = ''
  formStep.value = 'forgot-password'
}

function backToCredentials() {
  ticket.value = ''
  code.value = ''
  formStep.value = 'credentials'
}

async function onSubmit() {
  if (loading.value) return
  errorMsg.value = ''
  loading.value = true
  try {
    const response = await auth.login(email.value, password.value)
    if (response.twoFARequired) {
      ticket.value = response.ticket ?? ''
      code.value = ''
      formStep.value = 'two-factor'
      return
    }
    if (response.forcePasswordChange) {
      await navigateTo({ path: '/force-change-password', query: { redirect: getPostLoginPath() } })
      return
    }
    await finishLogin()
  } catch (error) {
    const status = getErrorStatus(error)
    if (status === 429) {
      errorMsg.value = 'Слишком много попыток входа. Попробуйте через 15 минут.'
    } else if (status === 401 || status === 403) {
      errorMsg.value = 'Неверный email или пароль.'
    } else if (!status || status === 0) {
      errorMsg.value = 'Сервис недоступен. Попробуйте позже.'
    } else {
      errorMsg.value = 'Не удалось войти. Попробуйте позже.'
    }
  } finally {
    loading.value = false
  }
}

async function finishLogin() {
  const redirect = getPostLoginPath()
  if (auth.isClient && auth.user?.consent_accepted === false) {
    await navigateTo({ path: '/consent', query: { redirect } })
    return
  }
  await navigateTo(redirect)
}

async function onVerify() {
  if (loading.value) return
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.verify2fa(ticket.value, code.value.trim())
    if (auth.user?.forcePasswordChange) {
      await navigateTo({ path: '/force-change-password', query: { redirect: getPostLoginPath() } })
      return
    }
    await finishLogin()
  } catch (error) {
    errorMsg.value = getErrorStatus(error) === 401
      ? 'Неверный код. Проверьте код в приложении или используйте recovery-код.'
      : getErrorMessage(error, 'Ошибка подтверждения', { nested: true, withMessage: true })
  } finally {
    loading.value = false
  }
}

async function onForgotPassword() {
  if (forgotLoading.value) return
  forgotLoading.value = true
  forgotError.value = ''
  try {
    await request('/api/v1/auth/forgot-password', {
      method: 'POST',
      body: { email: forgotEmail.value.trim() },
    })
    forgotSent.value = true
  } catch (error) {
    forgotError.value = getErrorMessage(error, 'Не удалось отправить запрос. Попробуйте позже.')
  } finally {
    forgotLoading.value = false
  }
}
</script>

<template>
  <div>
    <template v-if="formStep === 'credentials'">
      <PageHeading
        eyebrow="Шаг 1 из 2"
        title="Вход в кабинет"
        description="Используйте email и пароль, выданные менеджером."
      />

      <form class="space-y-5" @submit.prevent="onSubmit">
        <p
          v-if="errorMsg"
          class="border border-danger/40 bg-danger-soft px-3 py-2.5 text-sm text-danger-text"
          role="alert"
          data-testid="login-error"
        >
          {{ errorMsg }}
        </p>
        <UiField for="email" label="Email" required>
          <UiInput
            id="email"
            v-model="email"
            type="email"
            required
            autocomplete="username"
            :disabled="loading"
          />
        </UiField>
        <UiField for="password" label="Пароль" required>
          <UiInput
            id="password"
            v-model="password"
            type="password"
            required
            autocomplete="current-password"
            :disabled="loading"
          />
        </UiField>

        <div class="flex flex-col gap-3 border-y border-border py-4 sm:flex-row sm:items-center sm:justify-between">
          <UiCheckbox v-model="remember" label="Запомнить меня" :disabled="loading" />
          <button type="button" class="min-h-11 text-left text-sm font-semibold text-action underline underline-offset-4" @click="openForgotPassword">
            Забыли пароль?
          </button>
        </div>

        <UiButton type="submit" size="touch" class="w-full" :loading="loading" :disabled="loading">
          {{ loading ? 'Проверяем данные' : 'Продолжить' }}
        </UiButton>
      </form>

      <div class="mt-7 flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-sm text-ink-muted">Нет доступа? Запросите учётную запись у менеджера.</p>
        <UiButton variant="outline" size="touch" @click="showContactModal = true">Связаться</UiButton>
      </div>
    </template>

    <template v-else-if="formStep === 'two-factor'">
      <PageHeading
        eyebrow="Шаг 2 из 2"
        title="Подтвердите вход"
        :description="`Введите код из приложения или recovery-код для ${email}.`"
      />

      <form class="space-y-5" @submit.prevent="onVerify">
        <UiField
          for="twofa-code"
          label="Код подтверждения"
          required
          :description="code.length === 0 ? 'Код приложения состоит из шести цифр.' : undefined"
          :error="errorMsg || undefined"
        >
          <UiInput
            id="twofa-code"
            v-model="code"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            minlength="6"
            maxlength="10"
            monospace
            class="text-center text-lg tracking-[0.24em]"
            placeholder="000000"
            :disabled="loading"
          />
        </UiField>
        <div class="flex flex-col gap-3 sm:flex-row">
          <UiButton type="submit" size="touch" class="flex-1" :loading="loading" :disabled="loading || code.trim().length < 6">
            {{ loading ? 'Проверяем' : 'Подтвердить вход' }}
          </UiButton>
          <UiButton variant="outline" size="touch" :disabled="loading" @click="backToCredentials">Назад</UiButton>
        </div>
      </form>
    </template>

    <template v-else>
      <PageHeading
        eyebrow="Восстановление доступа"
        title="Запросить ссылку"
        description="Укажите email: если он зарегистрирован, система отправит ссылку для смены пароля."
      />

      <div v-if="forgotSent" class="border border-success/40 bg-success-soft p-4" role="status">
        <h3 class="font-bold text-success-text">Запрос принят</h3>
        <p class="mt-2 text-sm text-success-text">Если email зарегистрирован, ссылка для сброса отправлена на него.</p>
      </div>
      <form v-else class="space-y-5" @submit.prevent="onForgotPassword">
        <UiField for="forgot-email" label="Email" required :error="forgotError || undefined">
          <UiInput
            id="forgot-email"
            v-model="forgotEmail"
            type="email"
            required
            autocomplete="username"
            :disabled="forgotLoading"
          />
        </UiField>
        <UiButton type="submit" size="touch" class="w-full" :loading="forgotLoading" :disabled="forgotLoading">
          {{ forgotLoading ? 'Отправляем' : 'Отправить ссылку' }}
        </UiButton>
      </form>
      <UiButton variant="ghost" class="mt-5" @click="backToCredentials">Вернуться ко входу</UiButton>
    </template>

    <ManagerContactModal :show="showContactModal" @close="showContactModal = false" />
  </div>
</template>
