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
    <section class="w-full max-w-md border border-border bg-surface p-8 text-center sm:p-10" aria-labelledby="error-title">
      <p class="numeric mb-3 text-5xl font-bold text-action">{{ error.statusCode }}</p>
      <h1 id="error-title" class="mb-2 text-xl font-semibold">{{ title }}</h1>
      <p class="mb-6 text-sm text-ink-muted">{{ hint }}</p>
      <button type="button" class="btn-primary min-h-11 px-6 py-3" @click="handleHome">На главную</button>
    </section>
  </div>
</template>
