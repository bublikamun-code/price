<script setup lang="ts">
// Сброс пароля по токену из письма (POST /auth/forgot-password, §16 п.19).
// Токен приходит в query (?token=...), ответ бэкенда — 200 или 400 «ссылка недействительна».
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
const passwordsValid = computed(
  () => password.value.length >= 8 && password.value === password2.value,
)

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
  } catch (e) {
    // 400 — токен неизвестен/использован/истёк: бейдж + ссылка «Запросить заново».
    errorMsg.value = getErrorMessage(e, 'Не удалось сменить пароль. Попробуйте позже.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card p-8">
    <h1 class="text-2xl font-bold text-center mb-2">Новый пароль</h1>
    <p class="text-sm text-ink-muted text-center mb-8">Придумайте новый пароль для входа</p>

    <template v-if="tokenMissing && !success">
      <div class="badge-danger w-full justify-center py-2 mb-4">
        Ссылка недействительна: не хватает токена сброса.
      </div>
      <NuxtLink to="/login" class="btn-primary w-full justify-center py-3">Запросить новую ссылку</NuxtLink>
    </template>

    <template v-else-if="success">
      <div class="badge-success w-full justify-center py-2.5 mb-6">
        Пароль обновлён. Теперь войдите с новым паролем.
      </div>
      <NuxtLink to="/login" class="btn-primary w-full justify-center py-3">Войти</NuxtLink>
    </template>

    <form v-else class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <div>
        <label class="label" for="new-password">Новый пароль</label>
        <input id="new-password" v-model="password" type="password" required minlength="8" autocomplete="new-password" class="input" placeholder="••••••••" >
        <p class="text-xs text-ink-faint mt-1.5">Минимум 8 символов.</p>
      </div>
      <div>
        <label class="label" for="new-password2">Повторите пароль</label>
        <input id="new-password2" v-model="password2" type="password" required autocomplete="new-password" class="input" placeholder="••••••••" >
        <p v-if="password2 && password !== password2" class="text-xs text-danger mt-1.5">Пароли не совпадают.</p>
      </div>

      <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">
        {{ errorMsg }}
        <NuxtLink to="/login" class="underline ml-1 whitespace-nowrap">Запросить заново</NuxtLink>
      </div>

      <button type="submit" class="btn-primary w-full py-3" :disabled="loading || !passwordsValid">
        <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ loading ? 'Сохранение...' : 'Сохранить пароль' }}
      </button>
    </form>

    <p class="text-xs text-ink-faint text-center mt-6">
      Ссылка действует ограниченное время. Если она устарела — запросите сброс ещё раз.
    </p>
  </div>
</template>
