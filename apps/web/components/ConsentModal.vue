<script setup lang="ts">
// Модал согласия на обработку ПДн (SITEMAP /consent, §11).
// Показывается клиенту, пока auth.user.consent_accepted === false;
// принятие — PATCH /auth/me (consent_accepted: true) через useAuth.updateMe.
const auth = useAuth()

const accepted = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const dismissed = ref(false)
const dialog = ref<HTMLElement | null>(null)
const consentCheckbox = ref<HTMLInputElement | null>(null)
let previousFocus: HTMLElement | null = null
let previousOverflow = ''
let dialogOpen = false

const show = computed(
  () => !dismissed.value && auth.isAuthenticated && auth.isClient && auth.user?.consent_accepted === false,
)

function close() {
  // Escape оставляет возможность вернуться к согласию на текущей сессии.
  dismissed.value = true
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && !loading.value) {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return

  // Цикл фокуса не позволяет уйти из обязательного диалога на элементы страницы.
  const focusable = Array.from(dialog.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter(el => !el.hasAttribute('hidden') && el.offsetParent !== null)
  if (!focusable.length) {
    event.preventDefault()
    dialog.value.focus()
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(show, (open) => {
  // В SSR модалка ещё не существует, поэтому обращаться к DOM можно только на клиенте.
  if (!import.meta.client) return
  if (open) {
    dialogOpen = true
    previousFocus = document.activeElement as HTMLElement | null
    previousOverflow = document.body.style.overflow
    // Диалог блокирует прокрутку фона, пока пользователь не выразил согласие.
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    nextTick(() => consentCheckbox.value?.focus())
  } else if (dialogOpen) {
    dialogOpen = false
    document.removeEventListener('keydown', onKey)
    document.body.style.overflow = previousOverflow
    if (previousFocus?.isConnected) previousFocus.focus()
  }
}, { immediate: true })

onUnmounted(() => {
  if (!import.meta.client) return
  document.removeEventListener('keydown', onKey)
  if (dialogOpen) {
    dialogOpen = false
    document.body.style.overflow = previousOverflow
    if (previousFocus?.isConnected) previousFocus.focus()
  }
})

async function accept() {
  if (!accepted.value || loading.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await auth.updateMe({ consent_accepted: true })
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось сохранить согласие. Попробуйте ещё раз.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-4"
        aria-modal="true"
        role="dialog"
        aria-labelledby="consent-modal-title"
      >
        <div class="absolute inset-0" aria-hidden="true" />
        <div
          ref="dialog"
          class="relative max-h-[90vh] w-full max-w-xl overflow-y-auto border border-border-strong bg-surface p-6 sm:p-8"
          tabindex="-1"
        >
          <h1 id="consent-modal-title" class="text-2xl font-bold text-center mb-2">Согласие на обработку персональных данных</h1>
          <p class="text-sm text-ink-muted text-center mb-6">
            Для работы портала нам нужно ваше согласие. Краткая выжимка политики:
          </p>
          <ul class="flex flex-col gap-3 text-sm text-ink mb-6">
            <li class="flex gap-3">
              <Icon name="heroicons:shield-check" class="w-5 h-5 shrink-0 text-primary" />
              <span>Мы обрабатываем ваши ФИО, контакты и данные компании исключительно для оформления заявок и отображения персональных цен.</span>
            </li>
            <li class="flex gap-3">
              <Icon name="heroicons:lock-closed" class="w-5 h-5 shrink-0 text-primary" />
              <span>Обработка осуществляется в соответствии с Законом РБ «О защите персональных данных» — сбор, хранение, использование, обезличивание.</span>
            </li>
            <li class="flex gap-3">
              <Icon name="heroicons:eye-slash" class="w-5 h-5 shrink-0 text-primary" />
              <span>Персональные данные не передаются третьим лицам, кроме случаев, предусмотренных законодательством РБ.</span>
            </li>
            <li class="flex gap-3">
              <Icon name="heroicons:arrow-path" class="w-5 h-5 shrink-0 text-primary" />
              <span>Согласие можно отозвать — обратитесь к вашему менеджеру; данные удаляются/уничтожаются в установленный срок.</span>
            </li>
          </ul>
          <form class="flex flex-col gap-4" @submit.prevent="accept">
            <label class="flex items-start gap-3 text-sm cursor-pointer">
              <input
                id="consent-accepted"
                ref="consentCheckbox"
                v-model="accepted"
                type="checkbox"
                :aria-invalid="Boolean(errorMsg)"
                :aria-describedby="errorMsg ? 'consent-error' : undefined"
                class="mt-0.5 w-4 h-4 rounded border-border text-primary focus:ring-primary/30"
              >
              <span>
                Принимаю
                <NuxtLink to="/privacy" target="_blank" class="text-primary hover:underline">
                  условия обработки персональных данных
                </NuxtLink>
              </span>
            </label>
            <div v-if="errorMsg" id="consent-error" role="alert" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>
            <button type="submit" class="btn-primary w-full py-3" :disabled="loading || !accepted">
              <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              {{ loading ? 'Сохранение...' : 'Продолжить' }}
            </button>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
