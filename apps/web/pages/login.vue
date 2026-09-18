<script setup lang="ts">
// Страница входа. См. SITEMAP.md §5. При включённой у менеджера 2FA (§16 п.22)
// логин двухшаговый: email+пароль → ticket → код приложения/recovery → токены.
definePageMeta({ layout: 'auth' })
useHead({ title: 'Вход' })

const showContactModal = ref(false)
const email = ref('')
const password = ref('')
const remember = ref(true)
const loading = ref(false)
const errorMsg = ref('')

// Второй шаг 2FA (фича H): ticket из login + код из приложения или recovery-код.
const step = ref<1 | 2>(1)
const ticket = ref('')
const code = ref('')

const auth = useAuth()
const route = useRoute()
const codeInput = ref<HTMLInputElement | null>(null)

// «Забыли пароль?»: инлайн-форма → POST /auth/forgot-password (ответ всегда 202).
const showForgot = ref(false)
const forgotEmail = ref('')
const forgotLoading = ref(false)
const forgotSent = ref(false)
const forgotError = ref('')

async function onForgotPassword() {
  if (forgotLoading.value) return
  forgotLoading.value = true
  forgotError.value = ''
  const { request } = useApi()
  try {
    await request('/api/v1/auth/forgot-password', {
      method: 'POST',
      body: { email: forgotEmail.value.trim() },
    })
    // Бэкенд всегда отвечает 202 (не раскрываем наличие email в базе).
    forgotSent.value = true
  } catch (e) {
    forgotError.value = getErrorMessage(e, 'Не удалось отправить запрос. Попробуйте позже.')
  } finally {
    forgotLoading.value = false
  }
}

function openForgot() {
  showForgot.value = true
  forgotSent.value = false
  forgotEmail.value = ''
  forgotError.value = ''
}

// На втором шаге сразу фокусируемся на поле кода.
watch(step, (s) => {
  if (s === 2) nextTick(() => codeInput.value?.focus())
})

/** Общий пост-логин путь (после login или verify2fa): consent → redirect. */
async function finishLogin() {
  // Непринятое согласие (клиент) → сначала /consent, redirect-запрос игнорируем:
  // после принятия consent.global.ts всё равно не пропустит дальше без согласия.
  if (auth.isClient && auth.user?.consent_accepted === false) {
    await navigateTo('/consent')
    return
  }
  const redirect = (route.query.redirect as string) || (auth.isManager ? '/manager' : '/catalog')
  await navigateTo(redirect)
}

async function onSubmit() {
  errorMsg.value = ''
  loading.value = true
  try {
    const res = await auth.login(email.value, password.value)
    if (res.twoFARequired) {
      // 200 без токенов: нужен второй шаг (код из приложения / recovery-код).
      ticket.value = res.ticket ?? ''
      code.value = ''
      step.value = 2
      return
    }
    await finishLogin()
  } catch (e) {
    // Маппинг по HTTP-статусу вместо сырого текста ошибки API.
    const status = getErrorStatus(e)
    if (status === 429) {
      errorMsg.value = 'Слишком много попыток входа. Попробуйте через 15 минут.'
    } else if (status === 401 || status === 403) {
      errorMsg.value = 'Неверный email или пароль.'
    } else if (!status || status === 0) {
      // Нет HTTP-статуса — сетевая ошибка / API недоступен.
      errorMsg.value = 'Сервис недоступен. Попробуйте позже.'
    } else {
      errorMsg.value = 'Не удалось войти. Попробуйте позже.'
    }
  } finally {
    loading.value = false
  }
}

async function onVerify() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.verify2fa(ticket.value, code.value.trim())
    await finishLogin()
  } catch (e) {
    // 401 — неверный/просроченный код или ticket; показываем инлайн, шаг остаётся.
    errorMsg.value = getErrorStatus(e) === 401
      ? 'Неверный код. Проверьте код в приложении или используйте recovery-код.'
      : getErrorMessage(e, 'Ошибка подтверждения', { nested: true, withMessage: true })
  } finally {
    loading.value = false
  }
}

/** Назад к шагу 1: сбросить код/ticket (пароль вводим заново из соображений безопасности). */
function backToStep1() {
  step.value = 1
  ticket.value = ''
  code.value = ''
  errorMsg.value = ''
}
</script>

<template>
  <div class="card p-5 sm:p-8">
    <h1 class="text-2xl font-bold text-center mb-2">С возвращением</h1>
    <p class="text-sm text-ink-muted text-center mb-8">
      {{ step === 1 ? 'Войдите по данным, выданным менеджером' : 'Подтвердите вход кодом' }}
    </p>

    <!-- Шаг 1: email + пароль -->
    <form v-if="step === 1" class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <div>
        <label class="label" for="email">Email</label>
        <input id="email" v-model="email" type="email" required autocomplete="username" class="input" placeholder="you@company.by" >
      </div>
      <div>
        <label class="label" for="password">Пароль</label>
        <input id="password" v-model="password" type="password" required autocomplete="current-password" class="input" placeholder="••••••••" >
      </div>
      <div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-2">
        <label class="flex items-center gap-2 text-sm text-ink-muted cursor-pointer">
          <input v-model="remember" type="checkbox" class="rounded border-border" >
          Запомнить меня
        </label>
        <button
          type="button"
          class="text-sm text-primary hover:underline transition-colors duration-150"
          @click="showContactModal = true"
        >Связаться с менеджером</button>
      </div>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">
        {{ errorMsg }}
      </div>

      <button type="submit" class="btn-primary w-full py-3" :disabled="loading">
        <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ loading ? 'Вход...' : 'Войти' }}
      </button>

      <!-- Забыли пароль: ссылка → инлайн-форма сброса (POST /auth/forgot-password) -->
      <div class="text-center">
        <button
          v-if="!showForgot"
          type="button"
          class="text-sm text-primary hover:underline"
          @click="openForgot"
        >Забыли пароль?</button>
        <div v-else-if="forgotSent" class="badge-success w-full justify-center py-2 text-sm">
          Если email зарегистрирован, мы отправили ссылку для сброса.
        </div>
        <form v-else class="flex flex-col gap-3 mt-1" @submit.prevent="onForgotPassword">
          <p class="text-xs text-ink-faint">
            Укажите email — пришлём ссылку для восстановления пароля.
          </p>
          <input
            v-model="forgotEmail"
            type="email"
            required
            autocomplete="username"
            class="input"
            placeholder="you@company.by"
          >
          <div v-if="forgotError" class="badge-danger w-full justify-center py-2">{{ forgotError }}</div>
          <button type="submit" class="btn-outline w-full justify-center" :disabled="forgotLoading">
            <span v-if="forgotLoading" class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-full animate-spin"/>
            {{ forgotLoading ? 'Отправка…' : 'Отправить ссылку' }}
          </button>
          <button type="button" class="text-xs text-ink-muted hover:text-ink" @click="showForgot = false">
            Отмена
          </button>
        </form>
      </div>
    </form>

    <!-- Шаг 2: код из приложения (или recovery-код) -->
    <form v-else class="flex flex-col gap-4" @submit.prevent="onVerify">
      <p class="text-sm text-ink-muted">
        Включена двухфакторная аутентификация. Введите код из приложения-аутентификатора
        <span class="text-ink font-medium">({{ email }})</span>.
      </p>
      <div>
        <label class="label" for="twofa-code">Код из приложения (или recovery-код)</label>
        <input
          id="twofa-code"
          ref="codeInput"
          v-model="code"
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
          minlength="6"
          maxlength="10"
          class="input font-mono tracking-widest text-center text-lg"
          placeholder="000000"
        >
        <p class="text-xs text-ink-faint mt-1.5">
          Не работает код? Введите один из recovery-кодов, полученных при включении 2FA.
        </p>
      </div>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">
        {{ errorMsg }}
      </div>

      <div class="flex flex-col gap-2">
        <button type="submit" class="btn-primary w-full py-3" :disabled="loading || code.trim().length < 6">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
          {{ loading ? 'Проверка...' : 'Подтвердить' }}
        </button>
        <button type="button" class="btn-ghost w-full justify-center" :disabled="loading" @click="backToStep1">
          Назад
        </button>
      </div>
    </form>

    <p class="text-xs text-ink-faint text-center mt-6">
      Нет доступа? Обратитесь к вашему менеджеру для создания учётной записи.
    </p>

    <ManagerContactModal :show="showContactModal" @close="showContactModal = false" />
  </div>
</template>
