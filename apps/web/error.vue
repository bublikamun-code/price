<script setup lang="ts">
// Кастомная страница ошибок. См. SITEMAP.md §10.
import { computed } from 'vue'
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()
useHead({ title: 'Ошибка' })

const title = computed(() => {
  if (props.error.statusCode === 404) return 'Страница не найдена'
  if (props.error.statusCode === 403) return 'Недостаточно прав'
  return 'Что-то пошло не так'
})

const hint = computed(() => {
  if (props.error.statusCode === 404) return 'Проверьте адрес или вернитесь на главную'
  if (props.error.statusCode === 403) return 'У вас нет доступа к этому разделу. Если он нужен — обратитесь к менеджеру.'
  return 'Мы уже разбираемся.'
})

function handleHome() {
  clearError({ redirect: '/' })
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-canvas px-4">
    <div class="card p-10 text-center max-w-md w-full">
      <p class="text-6xl font-bold text-primary mb-3">{{ error.statusCode }}</p>
      <h1 class="text-xl font-semibold mb-2">{{ title }}</h1>
      <p class="text-sm text-ink-muted mb-6">{{ hint }}</p>
      <button class="btn-primary px-6 py-3" @click="handleHome">На главную</button>
    </div>
  </div>
</template>
