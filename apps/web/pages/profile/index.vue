<script setup lang="ts">
// Профиль: личные данные (readonly) + валюта отображения цен.
// Сохранение: PATCH /api/v1/auth/me (через auth.updateMe). См. SITEMAP.md §5.
definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Профиль' })

const auth = useAuth()

const CURRENCIES = ['BYN', 'USD', 'EUR', 'RUB']

// Локальная копия для формы; init из стора (hydrate из cookie + fetchMe).
// '??' — на случай устаревшей cookie без новых полей.
const savedCurrency = () => auth.user?.displayCurrency || 'BYN'
const currency = ref(savedCurrency())
const loading = ref(false)
const errorMsg = ref('')
const saved = ref(false)

// Кнопка активна только при реальном изменении.
const dirty = computed(() => currency.value !== savedCurrency())

// Изменили селектор — убираем прошлые сообщения.
watch(currency, () => {
  saved.value = false
  errorMsg.value = ''
})

// fetchMe после загрузки обновил стор → подтягиваем, если форму не трогали.
watch(() => auth.user, () => {
  if (!dirty.value) currency.value = savedCurrency()
})

async function onSave() {
  if (loading.value || !dirty.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await auth.updateMe({ display_currency: currency.value })
    saved.value = true
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось сохранить настройки')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <!-- Заголовок + ссылка на уведомления -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <h1 class="text-2xl font-bold">Профиль</h1>
      <NuxtLink to="/profile/notifications" class="btn-ghost">
        <Icon name="heroicons:bell" class="w-4 h-4" />
        Настройки уведомлений
      </NuxtLink>
    </div>

    <div class="grid gap-6 lg:grid-cols-2 items-start">
      <!-- Личные данные (readonly) -->
      <div class="card p-5">
        <h3 class="font-semibold mb-3">Личные данные</h3>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">ФИО</span>
          <span class="font-medium">{{ auth.user?.name || '—' }}</span>
        </div>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Компания</span>
          <span class="font-medium">{{ auth.user?.company || '—' }}</span>
        </div>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Телефон</span>
          <span class="font-medium">{{ auth.user?.phone || '—' }}</span>
        </div>
        <div class="flex justify-between text-sm py-1.5">
          <span class="text-ink-muted">Email</span>
          <span class="font-medium">{{ auth.user?.email || '—' }}</span>
        </div>
        <p class="text-xs text-ink-faint mt-3">
          Для изменения данных обратитесь к менеджеру.
        </p>
      </div>

      <!-- Отображение цен -->
      <div class="card p-5">
        <h3 class="font-semibold mb-3">Отображение цен</h3>
        <form class="flex flex-col gap-4" @submit.prevent="onSave">
          <div>
            <label class="label" for="display_currency">Валюта отображения</label>
            <select id="display_currency" v-model="currency" class="input">
              <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
            </select>
            <p class="text-xs text-ink-faint mt-1.5">
              Цены в каталоге пересчитываются по курсу Нацбанка.
            </p>
          </div>

          <div v-if="errorMsg" class="badge-danger w-full justify-center py-2">{{ errorMsg }}</div>

          <div class="flex items-center gap-3">
            <button type="submit" class="btn-primary" :disabled="loading || !dirty">
              <span v-if="loading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
              {{ loading ? 'Сохранение...' : 'Сохранить' }}
            </button>
            <span v-if="saved" class="text-sm font-medium text-success">Сохранено</span>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
