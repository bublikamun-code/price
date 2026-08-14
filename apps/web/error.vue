<script setup lang="ts">
// Кастомная страница ошибок. См. SITEMAP.md §10.
import type { NuxtError } from '#app'

defineProps<{ error: NuxtError }>()
useHead({ title: 'Ошибка' })

function handleHome() {
  clearError({ redirect: '/' })
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-canvas px-4">
    <div class="card p-10 text-center max-w-md w-full">
      <p class="text-6xl font-bold text-primary mb-3">{{ error.statusCode }}</p>
      <h1 class="text-xl font-semibold mb-2">
        {{ error.statusCode === 404 ? 'Страница не найдена' : 'Что-то пошло не так' }}
      </h1>
      <p class="text-sm text-ink-muted mb-6">
        {{ error.statusMessage || 'Попробуйте обновить страницу или вернуться позже.' }}
      </p>
      <button class="btn-primary px-6 py-3" @click="handleHome">На главную</button>
    </div>
  </div>
</template>
