<script setup lang="ts">
definePageMeta({ layout: 'auth' })
useSeoMeta({ title: 'Новый пароль' })

const route = useRoute()
const { request } = useApi()

const token = computed(() => String(route.query.token || ''))
const password = ref('')
const password2 = ref('')
const loading = ref(false)
const success = ref(false)
const errorMsg = ref('')

const tokenMissing = computed(() => !token.value)
const mismatch = computed(() => Boolean(password2.value) && password.value !== password2.value)
const passwordsValid = computed(() => password.value.length >= 8 && password.value === password2.value)

async function onSubmit() {
  if (loading.value || !passwordsValid.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await request('/api/v1/auth/reset-password', {
      method: 'POST',
      body: { token: token.value, new_password: password.value },
    })
    success.value = true
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
      <p class="text-sm font-semibold text-ink-muted">Восстановление доступа</p>
      <h2 class="mt-2 text-3xl font-bold tracking-tight">Новый пароль</h2>
      <p class="mt-3 text-base text-ink-muted">Задайте пароль, который будете использовать для следующего входа.</p>
    </header>

    <template v-if="tokenMissing && !success">
      <p class="mt-7 border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger-text" role="alert">
        Ссылка недействительна: не хватает токена сброса.
      </p>
      <NuxtLink to="/login" class="btn-primary mt-5 min-h-11 w-full">Запросить новую ссылку</NuxtLink>
    </template>

    <template v-else-if="success">
      <div class="mt-7 border border-success/40 bg-success-soft px-4 py-5" role="status">
        <h3 class="font-bold text-success-text">Пароль обновлён</h3>
        <p class="mt-2 text-sm text-success-text">Теперь войдите в кабинет с новым паролем.</p>
      </div>
      <NuxtLink to="/login" class="btn-primary mt-5 min-h-11 w-full">Войти</NuxtLink>
    </template>

    <form v-else class="mt-7 space-y-5" @submit.prevent="onSubmit">
      <div>
        <label for="new-password" class="label">Новый пароль</label>
        <input
          id="new-password"
          v-model="password"
          type="password"
          required
          minlength="8"
          autocomplete="new-password"
          class="input"
          :aria-invalid="Boolean(errorMsg) || mismatch"
          :aria-describedby="errorMsg ? 'reset-password-error' : 'new-password-hint'"
        >
        <p id="new-password-hint" class="mt-2 text-sm text-ink-muted">Минимум 8 символов.</p>
      </div>
      <div>
        <label for="new-password2" class="label">Повторите пароль</label>
        <input
          id="new-password2"
          v-model="password2"
          type="password"
          required
          minlength="8"
          autocomplete="new-password"
          class="input"
          :aria-invalid="mismatch || Boolean(errorMsg)"
          :aria-describedby="mismatch ? 'password-mismatch' : (errorMsg ? 'reset-password-error' : undefined)"
        >
        <p v-if="mismatch" id="password-mismatch" class="mt-2 text-sm text-danger-text" role="alert">Пароли не совпадают.</p>
      </div>

      <p v-if="errorMsg" id="reset-password-error" class="border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger-text" role="alert">
        {{ errorMsg }}
        <NuxtLink to="/login" class="ml-1 font-semibold underline underline-offset-4">Запросить заново</NuxtLink>
      </p>

      <button type="submit" class="btn-primary min-h-11 w-full" :disabled="loading || !passwordsValid">
        <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
        {{ loading ? 'Сохраняем' : 'Сохранить пароль' }}
      </button>
    </form>

    <p class="mt-6 border-t border-border pt-5 text-sm text-ink-muted">
      Ссылка имеет ограниченный срок действия. Если она устарела, запросите новую со страницы входа.
    </p>
  </div>
</template>
