<script setup lang="ts">
// Настройки уведомлений: дайджест изменения цен (in-app).
// Сохранение: PATCH /api/v1/auth/me (price_digest_enabled / price_digest_sources).
definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Настройки уведомлений' })

const auth = useAuth()

// Источники позиций для отслеживания (контракт /auth/me: cart|favorite|orders).
const SOURCES: { value: string; label: string }[] = [
  { value: 'cart', label: 'Корзина' },
  { value: 'favorite', label: 'Избранное' },
  { value: 'orders', label: 'Заказы' },
]

// Локальные копии для формы; init из стора (hydrate из cookie + fetchMe).
// '??' — на случай устаревшей cookie без новых полей.
const enabled = ref(auth.user?.priceDigestEnabled ?? false)
const sources = ref<string[]>([...(auth.user?.priceDigestSources ?? [])])
const loading = ref(false)
const errorMsg = ref('')
const saved = ref(false)

/** Одно и то же множество источников (порядок не важен). */
function sameSources(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every(x => b.includes(x))
}

const savedDigest = () => ({
  enabled: auth.user?.priceDigestEnabled ?? false,
  sources: auth.user?.priceDigestSources ?? [],
})

// Кнопка активна только при реальном изменении.
const dirty = computed(() => {
  const s = savedDigest()
  return enabled.value !== s.enabled || !sameSources(sources.value, s.sources)
})

// Изменили форму — убираем прошлые сообщения.
watch([enabled, sources], () => {
  saved.value = false
  errorMsg.value = ''
})

// fetchMe после загрузки обновил стор → подтягиваем, если форму не трогали.
watch(() => auth.user, () => {
  if (!dirty.value) {
    enabled.value = auth.user?.priceDigestEnabled ?? false
    sources.value = [...(auth.user?.priceDigestSources ?? [])]
  }
})

async function onSave() {
  if (loading.value || !dirty.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await auth.updateMe({
      price_digest_enabled: enabled.value,
      price_digest_sources: sources.value,
    })
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
    <!-- Хлебные крошки: Профиль / Уведомления -->
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/profile" class="hover:text-primary">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Уведомления</span>
    </nav>

    <h1 class="text-2xl font-bold mb-6">Настройки уведомлений</h1>

    <div class="card p-5 max-w-2xl">
      <h3 class="font-semibold mb-1">Дайджест изменения цен</h3>

      <form class="flex flex-col gap-4" @submit.prevent="onSave">
        <!-- Вкл/выкл дайджест -->
        <label class="flex items-center gap-2 text-sm cursor-pointer">
          <input v-model="enabled" type="checkbox" class="rounded border-border">
          Присылать дайджест при изменении цен на отслеживаемые товары
        </label>
        <p class="text-xs text-ink-faint">
          Уведомления появятся в колокольчике в кабинете.
        </p>

        <!-- Источники позиций -->
        <div :class="enabled ? '' : 'opacity-60'">
          <label class="label">Отслеживать позиции из</label>
          <label
            v-for="s in SOURCES"
            :key="s.value"
            class="flex items-center gap-2 text-sm py-1"
            :class="enabled ? 'cursor-pointer' : 'cursor-not-allowed'"
          >
            <input v-model="sources" type="checkbox" :value="s.value" class="rounded border-border" :disabled="!enabled">
            {{ s.label }}
          </label>
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
</template>
