<script setup lang="ts">
// Согласие на обработку персональных данных (однократно, после первого входа).
// PATCH /api/v1/auth/me {consent_accepted: true} → /catalog. См. SITEMAP.md §6 `/consent`.
definePageMeta({ layout: 'auth', middleware: ['auth', 'role'], roles: ['CLIENT'] })
useHead({ title: 'Согласие на обработку ПДн' })

const auth = useAuth()

const accepted = ref(false)
const loading = ref(false)
const errorMsg = ref('')

async function onSubmit() {
  if (loading.value || !accepted.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    // updateMe → applyUser: consent_accepted попадает в стор и в cookie auth_user.
    await auth.updateMe({ consent_accepted: true })
    await navigateTo('/catalog')
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось сохранить согласие')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card p-8">
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

    <form class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <label class="flex items-start gap-3 text-sm cursor-pointer">
        <input v-model="accepted" type="checkbox" class="mt-0.5 w-4 h-4 rounded border-border text-primary focus:ring-primary/30" >
        <span>Принимаю условия обработки персональных данных</span>
      </label>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">
        {{ errorMsg }}
      </div>

      <button type="submit" class="btn-primary w-full py-3" :disabled="loading || !accepted">
        <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ loading ? 'Сохранение...' : 'Продолжить' }}
      </button>
    </form>
  </div>
</template>
