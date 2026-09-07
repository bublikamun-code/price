<script setup lang="ts">
// Модал согласия на обработку ПДн (SITEMAP /consent, §11).
// Показывается клиенту, пока auth.user.consent_accepted === false;
// принятие — PATCH /auth/me (consent_accepted: true) через useAuth.updateMe.
const auth = useAuth()

const accepted = ref(false)
const loading = ref(false)
const errorMsg = ref('')

const show = computed(
  () => auth.isAuthenticated && auth.isClient && auth.user?.consent_accepted === false,
)

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
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/60 backdrop-blur-sm"
        aria-modal="true"
        role="dialog"
      >
        <div class="absolute inset-0" aria-hidden="true" />
        <div class="relative w-full max-w-xl max-h-[90vh] overflow-y-auto scrollbar-none card p-6 sm:p-8 shadow-card">
          <h1 class="text-2xl font-bold text-center mb-2">Согласие на обработку персональных данных</h1>
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
                v-model="accepted"
                type="checkbox"
                class="mt-0.5 w-4 h-4 rounded border-border text-primary focus:ring-primary/30"
              >
              <span>
                Принимаю
                <NuxtLink to="/privacy" target="_blank" class="text-primary hover:underline">
                  условия обработки персональных данных
                </NuxtLink>
              </span>
            </label>
            <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>
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
