<script setup lang="ts">
// Баннер согласия на cookie (гостям и пользователям, до выбора).
// Выбор хранится в localStorage — на устройстве пользователя, без бэкенда.
// На сайте только необходимые cookie (сессия/CSRF), аналитических нет.
const STORAGE_KEY = 'cookie_consent'

const visible = ref(false)

// В кабинете баннер встаёт над нижней навигацией, на публичных страницах —
// в самый низ. Высота навигации приходит из общего владельца нижних слоёв.
const { navLayerHeight, stickyLayerHeight } = useBottomLayers()
const laneStyle = computed(() => ({
  bottom: `calc(${navLayerHeight.value}px + ${stickyLayerHeight.value}px)`,
}))

// Пока баннер виден — освобождаем место над ним (иначе накрывает футер
// на коротких страницах; аудит UX 19.09)
watch(visible, (v) => {
  if (typeof document === 'undefined') return
  document.body.classList.toggle('has-cookie-banner', v)
}, { immediate: true })

onMounted(() => {
  try {
    if (!localStorage.getItem(STORAGE_KEY)) {
      // небольшая задержка: дать странице спокойно отрендериться
      setTimeout(() => { visible.value = true }, 700)
    }
  } catch {
    // localStorage недоступен (приватный режим) — показываем, выбор не сохранится
    visible.value = true
  }
})

function accept() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ accepted: true, at: new Date().toISOString() }))
  } catch {
    // ignore
  }
  visible.value = false
}
</script>

<template>
  <Teleport to="body">
    <Transition name="banner-slide">
      <div
        v-if="visible"
        class="pointer-events-none fixed inset-x-0 z-40"
        :style="laneStyle"
        role="region"
        aria-label="Уведомление об использовании cookie"
      >
        <div class="container-app pb-4">
          <div
            class="pointer-events-auto service-record max-w-3xl mx-auto flex flex-col sm:flex-row sm:items-center gap-4"
          >
            <Icon name="heroicons:lock-closed" class="w-6 h-6 shrink-0 text-action-on hidden sm:block" />
            <p class="text-sm text-ink-on-service leading-relaxed min-w-0">
              Мы используем необходимые cookie для работы портала: сессия входа,
              защита форм (CSRF) и ваши настройки. Аналитических и рекламных
              cookie нет.
              <NuxtLink
                to="/privacy"
                class="text-action-on hover:underline transition-colors duration-150 whitespace-nowrap"
              >Подробнее</NuxtLink>
            </p>
            <UiButton type="button" size="touch" class="shrink-0 px-5" @click="accept">
              Принять
            </UiButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.banner-slide-enter-active,
.banner-slide-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.banner-slide-enter-from,
.banner-slide-leave-to {
  opacity: 0;
  transform: translateY(16px);
}
</style>
