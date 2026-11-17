<script setup lang="ts">
definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Настройки уведомлений' })

const auth = useAuth()

const SOURCES: { value: string; label: string; description: string }[] = [
  { value: 'cart', label: 'Заявка', description: 'Товары, подготовленные к заказу.' },
  { value: 'favorite', label: 'Избранное', description: 'Сохранённые позиции каталога.' },
  { value: 'orders', label: 'Заказы', description: 'Позиции из оформленных заказов.' },
]

// Значения полей НЕ читаются из auth.user прямо в setup: на SSR профиль может
// быть ещё не подтверждён (access-токен истёк, а refresh на сервере запрещён —
// plugins/auth.session.ts), и сервер отдал бы «пустые» чекбоксы. На клиенте
// профиль к моменту setup уже есть, и разметка разошлась бы с серверной —
// Nuxt писал бы «Hydration completed but contains mismatches». Поэтому до
// монтирования обе версии рендерят одно и то же, а реальные значения
// подставляются после подтверждения сессии на клиенте.
const enabled = ref(false)
const sources = ref<string[]>([])
// Снимок последнего известного серверного состояния; null — «ещё не
// подтверждено». По нему считается «изменено», а не по auth.user: до
// подтверждения сессии auth.user пуст, и сравнение с ним давало бы разные
// результаты на сервере и на клиенте (например, кнопка «Сохранить» была бы
// disabled в одном рендере и активна в другом).
const persisted = ref<{ enabled: boolean; sources: string[] } | null>(null)
const loading = ref(false)
const errorMsg = ref('')
const saved = ref(false)

function sameSources(first: string[], second: string[]): boolean {
  return first.length === second.length && first.every((value) => second.includes(value))
}

const dirty = computed(() => {
  const current = persisted.value
  if (!current) return false
  return enabled.value !== current.enabled || !sameSources(sources.value, current.sources)
})

watch([enabled, sources], () => {
  saved.value = false
  errorMsg.value = ''
})

/**
 * Переносит профиль в поля формы.
 *
 * Помечает состояние «изменено» по ПРЕДЫДУЩЕМУ снимку: после подстановки
 * нового persisted сравнение шло бы уже с ним и всегда давало бы «изменено».
 */
function applyProfile() {
  const next = {
    enabled: auth.user?.priceDigestEnabled ?? false,
    sources: [...(auth.user?.priceDigestSources ?? [])],
  }
  const current = persisted.value
  const wasDirty = current
    ? enabled.value !== current.enabled || !sameSources(sources.value, current.sources)
    : false
  persisted.value = next
  if (!wasDirty) {
    enabled.value = next.enabled
    sources.value = [...next.sources]
  }
}

// Сессия подтверждается плагином до рендера, но на клиенте профиль приходит
// уже в setup — значит, синхронизируем поля после монтирования. До этого
// момента SSR и клиент показывают одно и то же.
onMounted(applyProfile)

watch(() => auth.user, () => {
  applyProfile()
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
  } catch (error) {
    errorMsg.value = getErrorMessage(error, 'Не удалось сохранить настройки')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl">
    <nav class="mb-6 flex items-center gap-2 text-sm text-ink-muted" aria-label="Хлебные крошки">
      <NuxtLink to="/profile" class="hover:text-action">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-4" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Уведомления</span>
    </nav>

    <PageHeading
      eyebrow="Параметры кабинета"
      title="Уведомления"
      description="Выберите, какие позиции отслеживать для уведомлений об изменении цены."
    />

    <form class="py-6" @submit.prevent="onSave">
      <section class="grid border-b border-border pb-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="digest-heading">
        <h2 id="digest-heading" class="text-sm font-bold text-ink">Дайджест цен</h2>
        <div>
          <label class="flex cursor-pointer items-start gap-3" for="digest-enabled">
            <input id="digest-enabled" v-model="enabled" type="checkbox" class="mt-0.5 size-4" :aria-describedby="enabled ? 'digest-description' : undefined">
            <span>
              <span class="font-semibold text-ink">Присылать уведомления об изменениях цен</span>
              <span id="digest-description" class="mt-1 block text-sm text-ink-muted">
                Сообщение появится в колокольчике кабинета.
              </span>
            </span>
          </label>
        </div>
      </section>

      <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="sources-heading">
        <div>
          <h2 id="sources-heading" class="text-sm font-bold text-ink">Источники</h2>
          <p class="mt-2 text-sm text-ink-muted">Доступны, когда дайджест включён.</p>
        </div>
        <fieldset :disabled="!enabled" class="divide-y divide-border border-y border-border">
          <legend class="sr-only">Источники отслеживаемых позиций</legend>
          <label
            v-for="source in SOURCES"
            :key="source.value"
            class="flex min-h-16 cursor-pointer items-center gap-3 py-3"
            :class="{ 'cursor-not-allowed opacity-60': !enabled }"
          >
            <input v-model="sources" type="checkbox" :value="source.value" class="size-4">
            <span>
              <span class="block font-semibold text-ink">{{ source.label }}</span>
              <span class="mt-0.5 block text-sm text-ink-muted">{{ source.description }}</span>
            </span>
          </label>
        </fieldset>
      </section>

      <div class="flex flex-col gap-3 pt-6 sm:flex-row sm:items-center sm:justify-between">
        <div aria-live="polite">
          <p v-if="errorMsg" class="text-sm font-semibold text-danger-text" role="alert">{{ errorMsg }}</p>
          <p v-else-if="saved" class="text-sm font-semibold text-success-text" role="status">Настройки сохранены.</p>
        </div>
        <button type="submit" class="btn-primary sm:min-w-40" :disabled="loading || !dirty">
          <span v-if="loading" class="size-4 animate-spin motion-reduce:animate-none rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
          {{ loading ? 'Сохраняем' : 'Сохранить' }}
        </button>
      </div>
    </form>
  </div>
</template>
