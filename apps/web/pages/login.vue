<script setup lang="ts">
// Страница входа. См. SITEMAP.md §5.
definePageMeta({ layout: 'auth' })
useHead({ title: 'Вход' })

const email = ref('')
const password = ref('')
const remember = ref(true)
const loading = ref(false)
const errorMsg = ref('')

const auth = useAuth()
const route = useRoute()

async function onSubmit() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    // Непринятое согласие (клиент) → сначала /consent, redirect-запрос игнорируем:
    // после принятия consent.global.ts всё равно не пропустит дальше без согласия.
    if (auth.isClient && auth.user?.consent_accepted === false) {
      await navigateTo('/consent')
      return
    }
    const redirect = (route.query.redirect as string) || (auth.isManager ? '/manager' : '/catalog')
    await navigateTo(redirect)
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Ошибка входа', { nested: true, withMessage: true })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card p-8">
    <h1 class="text-2xl font-bold text-center mb-2">С возвращением</h1>
    <p class="text-sm text-ink-muted text-center mb-8">Войдите по данным, выданным менеджером</p>

    <form class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <div>
        <label class="label" for="email">Email</label>
        <input id="email" v-model="email" type="email" required autocomplete="username" class="input" placeholder="you@company.by" >
      </div>
      <div>
        <label class="label" for="password">Пароль</label>
        <input id="password" v-model="password" type="password" required autocomplete="current-password" class="input" placeholder="••••••••" >
      </div>
      <div class="flex items-center justify-between">
        <label class="flex items-center gap-2 text-sm text-ink-muted cursor-pointer">
          <input v-model="remember" type="checkbox" class="rounded border-border" >
          Запомнить меня
        </label>
        <a href="#" class="text-sm text-primary hover:underline">Связаться с менеджером</a>
      </div>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">
        {{ errorMsg }}
      </div>

      <button type="submit" class="btn-primary w-full py-3" :disabled="loading">
        <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ loading ? 'Вход...' : 'Войти' }}
      </button>
    </form>

    <p class="text-xs text-ink-faint text-center mt-6">
      Нет доступа? Обратитесь к вашему менеджеру для создания учётной записи.
    </p>
  </div>
</template>
