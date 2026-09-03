<script setup lang="ts">
// Журнал активных сессий (фича I, §16 п.22; обе роли).
// GET /auth/sessions; DELETE /auth/sessions/{id}; DELETE /auth/sessions (все кроме текущей).
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

const currentSession = computed(() => items.value.find(s => s.current) ?? null)

/** Узнать человекочитаемое имя устройства из User-Agent. */
function deviceName(ua: string | null): string {
  if (!ua) return 'Неизвестное устройство'
  const browsers: [RegExp, string][] = [
    [/YaBrowser\/([\d.]+)/, 'Yandex Browser'],
    [/Edg(?:e|A|iOS)?\/([\d.]+)/, 'Edge'],
    [/OPR\/([\d.]+)/, 'Opera'],
    [/Firefox\/([\d.]+)/, 'Firefox'],
    [/Chrome\/([\d.]+)/, 'Chrome'],
    [/Version\/([\d.]+).*Safari/, 'Safari'],
  ]
  const oses: [RegExp, string][] = [
    [/Windows NT/, 'Windows'],
    [/Mac OS X/, 'macOS'],
    [/Android/, 'Android'],
    [/iPhone|iPad/, 'iOS'],
    [/Linux/, 'Linux'],
  ]
  const browser = browsers.find(([re]) => re.test(ua))?.[1]
  const os = oses.find(([re]) => re.test(ua))?.[1]
  return [browser, os].filter(Boolean).join(', ') || 'Неизвестное устройство'
}

function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}

async function loadSessions() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<SessionListResponse>('/api/v1/auth/sessions')
    items.value = res.data
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить сессии')
  } finally {
    loading.value = false
  }
}

/** Отзыв одной сессии (текущая — дополнительно чистит куки на бэкенде). */
async function revoke(id: string) {
  if (busyId.value || revokingAll.value) return
  busyId.value = id
  error.value = ''
  try {
    await request(`/api/v1/auth/sessions/${id}`, { method: 'DELETE' })
    await loadSessions()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось завершить сессию')
  } finally {
    busyId.value = null
  }
}

/** Отзыв всех сессий кроме текущей. */
async function revokeAll() {
  if (busyId.value || revokingAll.value) return
  revokingAll.value = true
  error.value = ''
  try {
    await request('/api/v1/auth/sessions', { method: 'DELETE' })
    await loadSessions()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось завершить сессии')
  } finally {
    revokingAll.value = false
  }
}

// SSR показывает скелетон; реальные данные — на клиенте (нужна refresh-кука).
onMounted(() => {
  // Косвенное обращение к стору, чтобы не дёргать список до гидрации cookie-refs.
  void auth
  loadSessions()
})
</script>

<template>
  <div>
    <!-- Хлебные крошки: Профиль / Активные сессии -->
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/profile" class="hover:text-primary">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Активные сессии</span>
    </nav>

    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Активные сессии</h1>
        <p class="text-sm text-ink-muted mt-1">
          Устройства, в которых выполнен вход в ваш кабинет. Завершите незнакомые.
        </p>
      </div>
      <button
        v-if="!loading && items.some(s => !s.current)"
        class="btn-outline shrink-0"
        :disabled="revokingAll || busyId !== null"
        @click="revokeAll"
      >
        <span v-if="revokingAll" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
        {{ revokingAll ? 'Завершение...' : 'Завершить все остальные' }}
      </button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="loadSessions">Повторить</button>
    </div>

    <!-- Скелетон при загрузке -->
    <div v-if="loading" class="card p-5">
      <div v-for="i in 3" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <!-- Пусто -->
    <div v-else-if="!items.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:device-phone-mobile" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>Нет активных сессий</p>
    </div>

    <!-- Таблица сессий -->
    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Устройство</th>
              <th class="px-4 py-3 font-medium">IP</th>
              <th class="px-4 py-3 font-medium">Последний вход</th>
              <th class="px-4 py-3 font-medium">Действует до</th>
              <th class="px-4 py-3 font-medium text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in items"
              :key="s.id"
              :class="[busyId === s.id ? 'opacity-60' : '', 'border-t border-border hover:bg-canvas/60']"
            >
              <td class="px-4 py-3">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="font-medium">{{ deviceName(s.user_agent) }}</span>
                  <span v-if="s.current" class="badge-success">
                    <Icon name="heroicons:check-circle" class="w-3.5 h-3.5" />
                    Текущая
                  </span>
                </div>
                <p class="text-xs text-ink-faint mt-0.5 max-w-[320px] truncate" :title="s.user_agent ?? ''">
                  {{ s.user_agent || '—' }}
                </p>
              </td>
              <td class="px-4 py-3 text-ink-muted font-mono text-xs whitespace-nowrap">{{ s.ip || '—' }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDateTime(s.created_at) }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDateTime(s.expires_at) }}</td>
              <td class="px-4 py-3 text-right">
                <button
                  v-if="!s.current"
                  class="btn-ghost text-danger text-sm"
                  :disabled="busyId !== null || revokingAll"
                  @click="revoke(s.id)"
                >
                  <span v-if="busyId === s.id" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                  {{ busyId === s.id ? 'Завершение...' : 'Завершить' }}
                </button>
                <span v-else class="text-xs text-ink-faint">Эта сессия</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <p v-if="currentSession" class="text-xs text-ink-faint mt-4">
      Завершить текущую сессию можно через выход из кабинета.
    </p>
  </div>
</template>
