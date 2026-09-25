<script setup lang="ts">
import type { SessionListResponse, SessionOut } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Активные сессии' })

const { request } = useApi()
const auth = useAuth()

const loading = ref(true)
const error = ref('')
const items = ref<SessionOut[]>([])
const busyId = ref<string | null>(null)
const revokingAll = ref(false)

const currentSession = computed(() => items.value.find((session) => session.current) ?? null)

function deviceName(userAgent: string | null): string {
  if (!userAgent) return 'Неизвестное устройство'
  const browsers: [RegExp, string][] = [
    [/YaBrowser\/([\d.]+)/, 'Yandex Browser'],
    [/Edg(?:e|A|iOS)?\/([\d.]+)/, 'Edge'],
    [/OPR\/([\d.]+)/, 'Opera'],
    [/Firefox\/([\d.]+)/, 'Firefox'],
    [/Chrome\/([\d.]+)/, 'Chrome'],
    [/Version\/([\d.]+).*Safari/, 'Safari'],
  ]
  const operatingSystems: [RegExp, string][] = [
    [/Windows NT/, 'Windows'],
    [/Mac OS X/, 'macOS'],
    [/Android/, 'Android'],
    [/iPhone|iPad/, 'iOS'],
    [/Linux/, 'Linux'],
  ]
  const browser = browsers.find(([expression]) => expression.test(userAgent))?.[1]
  const operatingSystem = operatingSystems.find(([expression]) => expression.test(userAgent))?.[1]
  return [browser, operatingSystem].filter(Boolean).join(', ') || 'Неизвестное устройство'
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadSessions() {
  loading.value = true
  error.value = ''
  try {
    const response = await request<SessionListResponse>('/api/v1/auth/sessions')
    items.value = response.data
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось загрузить сессии')
  } finally {
    loading.value = false
  }
}

async function revoke(id: string) {
  if (busyId.value || revokingAll.value) return
  busyId.value = id
  error.value = ''
  try {
    await request(`/api/v1/auth/sessions/${id}`, { method: 'DELETE' })
    await loadSessions()
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось завершить сессию')
  } finally {
    busyId.value = null
  }
}

async function revokeAll() {
  if (busyId.value || revokingAll.value) return
  revokingAll.value = true
  error.value = ''
  try {
    await request('/api/v1/auth/sessions', { method: 'DELETE' })
    await loadSessions()
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось завершить сессии')
  } finally {
    revokingAll.value = false
  }
}

onMounted(() => {
  // SSR shows the loading record; the browser request needs the refresh cookie.
  void auth
  void loadSessions()
})
</script>

<template>
  <div class="mx-auto max-w-6xl">
    <nav class="mb-6 flex items-center gap-2 text-sm text-ink-muted" aria-label="Хлебные крошки">
      <NuxtLink to="/profile" class="hover:text-action">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-4" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Активные сессии</span>
    </nav>

    <PageHeading
      eyebrow="Безопасность"
      title="Активные сессии"
      description="Устройства, с которых выполнен вход. Завершите сессии, которые больше не используете."
    >
      <template #actions>
        <UiButton v-if="!loading && items.some((session) => !session.current)" variant="outline" size="touch" :loading="revokingAll" :disabled="revokingAll || busyId !== null" @click="revokeAll">
          {{ revokingAll ? 'Завершаем' : 'Завершить остальные' }}
        </UiButton>
      </template>
    </PageHeading>

    <div v-if="error" class="flex flex-col gap-3 border-b border-danger/40 py-4 sm:flex-row sm:items-center sm:justify-between" role="alert">
      <p class="text-sm text-danger-text">{{ error }}</p>
      <button type="button" class="btn-outline shrink-0" @click="loadSessions">Повторить</button>
    </div>

    <div v-if="loading" class="divide-y divide-border border-b border-border" aria-busy="true" aria-label="Загрузка сессий">
      <div v-for="index in 3" :key="index" class="grid gap-3 py-4 md:grid-cols-[minmax(0,1fr)_10rem_10rem]">
        <div class="skeleton h-5 w-full max-w-sm" />
        <div class="skeleton h-5 w-full" />
        <div class="skeleton h-5 w-full" />
      </div>
    </div>

    <div v-else-if="!items.length" class="border-b border-border py-12" role="status">
      <Icon name="heroicons:device-phone-mobile" class="size-8 text-ink-muted" aria-hidden="true" />
      <h2 class="mt-3 text-lg font-bold text-ink">Активных сессий нет</h2>
      <p class="mt-1 text-sm text-ink-muted">Обновите страницу после следующего входа в кабинет.</p>
    </div>

    <div v-else class="overflow-x-auto border-b border-border">
      <table class="w-full min-w-[52rem] text-sm">
        <caption class="sr-only">Список активных сессий</caption>
        <thead>
          <tr class="border-b border-border-strong bg-surface-2 text-left text-ink-muted">
            <th scope="col" class="px-3 py-3 font-semibold">Устройство</th>
            <th scope="col" class="px-3 py-3 font-semibold">IP-адрес</th>
            <th scope="col" class="px-3 py-3 font-semibold">Создана</th>
            <th scope="col" class="px-3 py-3 font-semibold">Действует до</th>
            <th scope="col" class="px-3 py-3 text-right font-semibold">Действие</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="session in items" :key="session.id" :class="{ 'opacity-60': busyId === session.id }">
            <td class="px-3 py-4 align-top">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-semibold text-ink">{{ deviceName(session.user_agent) }}</span>
                <span v-if="session.current" class="badge-success">Текущая</span>
              </div>
              <p class="mt-1 max-w-sm truncate text-xs text-ink-muted" :title="session.user_agent ?? ''">
                {{ session.user_agent || 'User-Agent не указан' }}
              </p>
            </td>
            <td class="px-3 py-4 align-top font-mono text-xs text-ink">{{ session.ip || '—' }}</td>
            <td class="px-3 py-4 align-top whitespace-nowrap text-ink-muted">{{ formatDateTime(session.created_at) }}</td>
            <td class="px-3 py-4 align-top whitespace-nowrap text-ink-muted">{{ formatDateTime(session.expires_at) }}</td>
            <td class="px-3 py-4 text-right align-top">
              <button
                v-if="!session.current"
                type="button"
                class="btn-ghost text-danger-text"
                :disabled="busyId !== null || revokingAll"
                @click="revoke(session.id)"
              >
                <span v-if="busyId === session.id" class="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
                {{ busyId === session.id ? 'Завершаем' : 'Завершить' }}
              </button>
              <span v-else class="text-xs text-ink-muted">Текущий вход</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="currentSession" class="mt-4 text-sm text-ink-muted">
      Текущую сессию завершите кнопкой «Выйти» в профиле.
    </p>
  </div>
</template>
