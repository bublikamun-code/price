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
  // 8 цифр — LINK_CODE_LENGTH в apps/api/app/services/telegram_auth.py.
  if (!/^\d{8}$/.test(code)) {
    errorMsg.value = 'Введите 8-значный код из веб-кабинета'
    return
  }
  void tryAuth(code)
}
</script>

<template>
  <div class="flex min-h-[70vh] flex-col justify-center">
    <PageHeading
      eyebrow="Telegram · клиентский портал"
      title="Вход в Mini App"
      description="Доступ подтверждается Telegram или кодом из профиля веб-кабинета."
    />

    <div v-if="checking" class="flex min-h-28 items-center gap-3 border border-border bg-surface p-4 text-sm text-ink-muted" role="status">
      <span class="size-5 shrink-0 animate-spin border-2 border-ink-faint border-t-action" aria-hidden="true" />
      Проверяем данные Telegram…
    </div>

    <template v-else>
      <div v-if="!hasInitData" class="mb-4 border border-warning/50 bg-warning-soft p-3 text-sm text-ink" role="status">
        Откройте Mini App из Telegram. Для другого клиента используйте код связки.
      </div>
      <div v-if="notice" class="mb-4 border border-info/50 bg-info-soft p-3 text-sm text-ink" role="status">{{ notice }}</div>
      <div v-if="errorMsg" class="mb-4 border border-danger/50 bg-danger-soft p-3 text-sm text-ink" role="alert">{{ errorMsg }}</div>

      <form class="border border-border bg-surface p-4 sm:p-5" @submit.prevent="submit">
        <label class="flex flex-col gap-1.5 text-sm font-semibold text-ink" for="link_code">Код связки</label>
        <input
          id="link_code"
          v-model="linkCode"
          class="input numeric mt-1 min-h-11 text-center text-lg tracking-[0.4em]"
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="8"
          placeholder="00000000"
        >
        <p class="mt-1.5 text-xs leading-5 text-ink-muted">Профиль → Telegram в веб-кабинете.</p>
        <button type="submit" class="btn-primary mt-4 min-h-11 w-full justify-center" :disabled="submitting">
          <span v-if="submitting" class="size-4 animate-spin border-2 border-white/40 border-t-white" aria-hidden="true" />
          {{ submitting ? 'Вход…' : 'Войти по коду' }}
        </button>
      </form>
    </template>
  </div>
</template>
