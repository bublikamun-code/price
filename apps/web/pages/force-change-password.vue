<script setup lang="ts">
// Принудительная смена временного пароля (после создания/сброса менеджером).
// Флаг force_password_change приходит в login/verify2fa и /auth/me (§16 п.19).
definePageMeta({ layout: 'auth', middleware: 'auth' })
useHead({ title: 'Смена пароля' })

const auth = useAuth()
const route = useRoute()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function onSubmit() {
  if (loading.value) return
  errorMsg.value = ''
  if (newPassword.value !== confirmPassword.value) {
    errorMsg.value = 'Пароли не совпадают.'
    return
  }
  loading.value = true
  try {
    // Через стор: baseURL API + Authorization (Bearer из auth_token) + X-CSRF-Token
    // (бэкенд требует CSRF для мутаций с cookie-аутентификацией, аудит 2026-09-06).
    await auth.changePassword(currentPassword.value, newPassword.value)
    // Обновляем профиль (сбрасываем force_password_change) → дальше в кабинет.
    await auth.fetchMe()
    const redirect = (route.query.redirect as string) || (auth.isManager ? '/manager' : '/catalog')
    await navigateTo(redirect)
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось сменить пароль. Попробуйте позже.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card p-8">
    <h1 class="text-2xl font-bold text-center mb-2">Смените пароль</h1>
    <p class="text-sm text-ink-muted text-center mb-8">
      Для продолжения работы установите новый пароль.
    </p>

    <form class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <div>
        <label class="label" for="current-password">Текущий пароль</label>
        <input id="current-password" v-model="currentPassword" type="password" required autocomplete="current-password" class="input" placeholder="••••••••" >
      </div>
      <div>
        <label class="label" for="new-password">Новый пароль</label>
        <input id="new-password" v-model="newPassword" type="password" required autocomplete="new-password" class="input" placeholder="••••••••" >
      </div>
      <div>
        <label class="label" for="confirm-password">Повторите новый пароль</label>
        <input id="confirm-password" v-model="confirmPassword" type="password" required autocomplete="new-password" class="input" placeholder="••••••••" >
      </div>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>

      <button type="submit" class="btn-primary w-full py-3" :disabled="loading">
        <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ loading ? 'Сохранение...' : 'Сохранить пароль' }}
      </button>
    </form>
  </div>
</template>
