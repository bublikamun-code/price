<script setup lang="ts">
definePageMeta({ layout: 'auth', middleware: 'auth' })
useHead({ title: 'Смена пароля' })

const auth = useAuth()
const route = useRoute()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')
const mismatch = computed(() => Boolean(confirmPassword.value) && newPassword.value !== confirmPassword.value)

async function onSubmit() {
  if (loading.value) return
  errorMsg.value = ''
  if (newPassword.value !== confirmPassword.value) {
    errorMsg.value = 'Пароли не совпадают.'
    return
  }
  loading.value = true
  try {
    await auth.changePassword(currentPassword.value, newPassword.value)
    await auth.fetchMe()
    const redirect = getSafeRedirectPath(
      route.query.redirect,
      auth.isManager ? '/manager' : '/dashboard',
    )
    if (auth.isClient && auth.user?.consent_accepted === false) {
      await navigateTo({ path: '/consent', query: { redirect } })
      return
    }
    await navigateTo(redirect)
  } catch (error) {
    errorMsg.value = getErrorMessage(error, 'Не удалось сменить пароль. Попробуйте позже.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <header class="border-b border-border-strong pb-6">
      <p class="text-sm font-semibold text-ink-muted">Обязательный шаг</p>
      <h2 class="mt-2 text-3xl font-bold tracking-tight">Установите новый пароль</h2>
      <p class="mt-3 text-base text-ink-muted">После сохранения временный пароль больше не будет использоваться для входа.</p>
    </header>

    <form class="mt-7 space-y-5" @submit.prevent="onSubmit">
      <div>
        <label for="current-password" class="label">Текущий пароль</label>
        <input
          id="current-password"
          v-model="currentPassword"
          type="password"
          required
          autocomplete="current-password"
          class="input"
          :aria-invalid="Boolean(errorMsg)"
          :aria-describedby="errorMsg ? 'force-password-error' : undefined"
        >
      </div>
      <div>
        <label for="new-password" class="label">Новый пароль</label>
        <input
          id="new-password"
          v-model="newPassword"
          type="password"
          required
          minlength="8"
          autocomplete="new-password"
          class="input"
          :aria-invalid="Boolean(errorMsg) || mismatch"
          :aria-describedby="errorMsg ? 'force-password-error' : 'new-password-hint'"
        >
        <p id="new-password-hint" class="mt-2 text-sm text-ink-muted">Минимум 8 символов.</p>
      </div>
      <div>
        <label for="confirm-password" class="label">Повторите новый пароль</label>
        <input
          id="confirm-password"
          v-model="confirmPassword"
          type="password"
          required
          minlength="8"
          autocomplete="new-password"
          class="input"
          :aria-invalid="mismatch || Boolean(errorMsg)"
          :aria-describedby="mismatch ? 'password-mismatch' : (errorMsg ? 'force-password-error' : undefined)"
        >
        <p v-if="mismatch" id="password-mismatch" class="mt-2 text-sm text-danger-text" role="alert">Пароли не совпадают.</p>
      </div>

      <p v-if="errorMsg" id="force-password-error" class="border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger-text" role="alert">{{ errorMsg }}</p>

      <button type="submit" class="btn-primary min-h-11 w-full" :disabled="loading || mismatch">
        <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
        {{ loading ? 'Сохраняем' : 'Сохранить пароль' }}
      </button>
    </form>
  </div>
</template>
