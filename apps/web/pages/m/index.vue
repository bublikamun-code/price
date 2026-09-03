<script setup lang="ts">
// Вход в Mini App: Telegram initData либо код связки из веб-кабинета.
// useTelegram — composables/useTelegram.ts (см. его интерфейс).
definePageMeta({ layout: 'miniapp' })
useHead({ title: 'Вход' })
const auth = useAuth()
const tg = useTelegram()
const router = useRouter()

const checking = ref(true)
const hasInitData = ref(false)
const linkCode = ref('')
const submitting = ref(false)
const errorMsg = ref('')
const notice = ref('')

/** Общий вход: initData (+необязательный код связки) → токены → каталог Mini App. */
async function tryAuth(code: string): Promise<boolean> {
  submitting.value = true
  errorMsg.value = ''
  try {
    const res = await tg.telegramAuth(code)
    if (res.ok) {
      await router.push('/m/catalog')
      return true
    }
    errorMsg.value = res.message ?? 'Не удалось войти через Telegram'
    return false
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  tg.signalReady()
  // Сессия уже есть (cookie) — сразу в каталог.
  if (auth.isAuthenticated) {
    await router.push('/m/catalog')
    return
  }
  // Внутри Telegram: пробуем войти по initData без кода связки.
  try {
    if (tg.webApp() && tg.initData()) {
      hasInitData.value = true
      if (await tryAuth('')) return
    }
  } catch {
    // показываем форму с кодом связки
  }
  checking.value = false
})

function submit() {
  const code = linkCode.value.trim()
  if (!/^\d{6}$/.test(code)) {
    errorMsg.value = 'Введите 6-значный код из веб-кабинета'
    return
  }
  void tryAuth(code)
}
</script>

<template>
  <div class="flex flex-col min-h-[70vh] justify-center">
    <div class="text-center mb-6">
      <span class="inline-flex items-center justify-center w-14 h-14 rounded-pill bg-surface-2 text-primary mb-4">
        <Icon name="heroicons:paper-airplane" class="w-7 h-7" />
      </span>
      <h1 class="text-xl font-bold">Клиентский портал</h1>
      <p class="text-sm text-ink-muted mt-1">Mini App для Telegram</p>
    </div>

    <div v-if="checking" class="card p-6 flex flex-col items-center gap-3 text-ink-muted">
      <span class="w-6 h-6 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
      <p class="text-sm">Входим через Telegram…</p>
    </div>

    <template v-else>
      <div v-if="!hasInitData" class="badge-warning w-full justify-center py-2.5 mb-4">
        <Icon name="heroicons:exclamation-triangle" class="w-4 h-4" /> Откройте Mini App из Telegram
      </div>
      <div v-if="notice" class="badge-info w-full justify-center py-2.5 mb-4">{{ notice }}</div>
      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2.5 mb-4">{{ errorMsg }}</div>

      <form class="card p-5 flex flex-col gap-4" @submit.prevent="submit">
        <div>
          <label class="label" for="link_code">Код связки</label>
          <input
            id="link_code"
            v-model="linkCode"
            class="input text-center text-lg tracking-[0.4em] font-semibold"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="6"
            placeholder="000000"
          >
          <p class="text-xs text-ink-faint mt-1.5"> Профиль → Telegram в веб-кабинете. </p>
        </div>
        <button type="submit" class="btn-primary w-full justify-center py-3" :disabled="submitting">
          <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          {{ submitting ? 'Вход…' : 'Войти' }}
        </button>
      </form>
    </template>
  </div>
</template>
