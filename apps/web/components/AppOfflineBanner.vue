<script setup lang="ts">
// Индикатор обрыва связи.
//
// Зачем: каталог почти весь интерактивный (корзина, заявка, загрузка прайса), и
// при обрыве сети кнопка не даёт обратной связи — страница просто молчит. Пользователь
// думает, что приложение зависло, и начинает жать повторно.
//
// Показывается ТОЛЬКО после подтверждённого обрыва (событие 'offline'), а не по
// факту загрузки страницы без сети: иначе баннер встречает пользователя на входе
// и мешает понять, что нужно обновить страницу.
const { isOnline, showOfflineBanner, dismissOfflineBanner } = useOnline()

// Короткое подтверждение восстановления: сеть вернулась — но параллельных
// запросов могло оборваться, пользователю полезно это подтвердить.
const justOnline = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

watch(isOnline, (value) => {
  if (!value) {
    justOnline.value = false
    return
  }
  justOnline.value = true
  clearTimeout(timer)
  timer = setTimeout(() => {
    justOnline.value = false
  }, 4000)
})

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div
    v-if="justOnline"
    class="border-b border-success/40 bg-success-soft px-4 py-2"
    role="status"
    aria-live="polite"
  >
    <div class="mx-auto flex max-w-6xl items-center justify-center gap-2">
      <Icon name="heroicons:signal" class="size-4 text-success-text" aria-hidden="true" />
      <p class="text-sm text-ink">Соединение восстановлено</p>
    </div>
  </div>

  <div
    v-else-if="showOfflineBanner"
    class="border-b border-danger/40 bg-danger-soft px-4 py-2"
    role="alert"
  >
    <div class="mx-auto flex max-w-6xl items-center justify-center gap-2">
      <Icon
        name="heroicons:signal-slash"
        class="size-4 shrink-0 text-danger-text"
        aria-hidden="true"
      />
      <p class="text-sm text-ink">
        Нет соединения с интернетом. Изменения не сохранятся, пока связь не вернётся.
      </p>
      <button
        type="button"
        class="ml-1 shrink-0 text-sm underline underline-offset-2 hover:no-underline"
        @click="dismissOfflineBanner()"
      >
        Скрыть
      </button>
    </div>
  </div>
</template>