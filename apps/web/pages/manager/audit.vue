<script setup lang="ts">
// Журнал аудита (менеджер). Этап 8. GET /api/v1/manager/audit?action&actor_id&target_type.
import type { AuditPage, AuditRead } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Журнал аудита — Менеджер' })

const { request } = useApi()
const PER_PAGE = 20

// Подсказки для фильтра действий (datalist).
const ACTION_SUGGESTIONS = [
  'user.create',
  'user.update',
  'user.reset_password',
  'user.discount.update',
  'user.fixed_rate.set',
  'user.fixed_rate.reset',
  'currency.rate.manual',
  'order.status_change',
]
const TARGET_TYPE_SUGGESTIONS = ['user', 'order']

const loading = ref(true)
const error = ref('')
const items = ref<AuditRead[]>([])
const total = ref(0)
const page = ref(1)

// Поля ввода фильтров + применённые значения (по кнопке «Применить»).
const actionInput = ref('')
const targetTypeInput = ref('')
const appliedAction = ref('')
const appliedTargetType = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<AuditPage>('/api/v1/manager/audit', {
      query: {
        action: appliedAction.value || undefined,
        target_type: appliedTargetType.value || undefined,
        page: page.value,
        per_page: PER_PAGE,
      },
    })
    items.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить журнал аудита')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  appliedAction.value = actionInput.value.trim()
  appliedTargetType.value = targetTypeInput.value.trim()
  page.value = 1
  load()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// Окно пагинации (1 ... 4 5 6 ... 20)
function paginationWindow(total: number, current: number, window = 2): (number | '...')[] {
  const pages: (number | '...')[] = []
  const start = Math.max(2, current - window)
  const end = Math.min(total - 1, current + window)
  pages.push(1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  if (total > 1) pages.push(total)
  return pages
}

function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}

function shortId(id: string | null): string {
  return id ? id.slice(0, 8) : ''
}

// Компакт «было → стало»: JSON в одну строку, до 80 символов; полный JSON — в title.
function compactJson(v: Record<string, unknown> | null): string {
  if (!v) return ''
  try {
    return JSON.stringify(v)
  } catch {
    return '[не сериализуемо]'
  }
}

interface ChangeCell {
  text: string
  title: string
}

function changeCell(a: AuditRead): ChangeCell | null {
  const before = compactJson(a.before)
  const after = compactJson(a.after)
  if (!before && !after) return null
  let text = `${before || '—'} → ${after || '—'}`
  if (text.length > 80) text = `${text.slice(0, 80)}…`
  return { text, title: `Было: ${before || '—'}\nСтало: ${after || '—'}` }
}

// Строки таблицы с предвычисленной ячейкой изменения (changeCell — чистая, но дорогая).
const rows = computed(() => items.value.map((a) => ({ entry: a, change: changeCell(a) })))

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Журнал аудита</h1>
      <p class="text-sm text-ink-muted mt-1">
        <template v-if="!loading">{{ total }} записей</template>
        <template v-else>Загрузка…</template>
      </p>
    </div>

    <!-- Фильтры -->
    <form class="flex flex-col sm:flex-row flex-wrap gap-4 sm:items-end mb-6" @submit.prevent="applyFilters">
      <div class="sm:w-64">
        <label class="label" for="f-action">Действие</label>
        <input
          id="f-action"
          v-model="actionInput"
          type="text"
          class="input font-mono text-sm"
          placeholder="user.update"
          list="audit-actions"
        >
        <datalist id="audit-actions">
          <option v-for="a in ACTION_SUGGESTIONS" :key="a" :value="a"/>
        </datalist>
      </div>
      <div class="sm:w-48">
        <label class="label" for="f-target">Тип цели</label>
        <input
          id="f-target"
          v-model="targetTypeInput"
          type="text"
          class="input font-mono text-sm"
          placeholder="user"
          list="audit-target-types"
        >
        <datalist id="audit-target-types">
          <option v-for="t in TARGET_TYPE_SUGGESTIONS" :key="t" :value="t"/>
        </datalist>
      </div>
      <button type="submit" class="btn-primary shrink-0">Применить</button>
    </form>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 8" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!items.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:shield-check" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>Записей нет</p>
    </div>

    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Время</th>
              <th class="px-4 py-3 font-medium">Актёр</th>
              <th class="px-4 py-3 font-medium">Действие</th>
              <th class="px-4 py-3 font-medium">Цель</th>
              <th class="px-4 py-3 font-medium">Изменение</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.entry.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDateTime(r.entry.created_at) }}</td>
              <td class="px-4 py-3 whitespace-nowrap">{{ r.entry.actor_email || 'Система' }}</td>
              <td class="px-4 py-3 font-mono text-xs whitespace-nowrap">{{ r.entry.action }}</td>
              <td class="px-4 py-3 font-mono text-xs whitespace-nowrap">
                <template v-if="r.entry.target_type">
                  {{ r.entry.target_type }}<template v-if="r.entry.target_id">:{{ shortId(r.entry.target_id) }}</template>
                </template>
                <template v-else><span class="text-ink-faint">—</span></template>
              </td>
              <td class="px-4 py-3 max-w-[320px]">
                <span
                  v-if="r.change"
                  class="font-mono text-xs text-ink-muted block truncate cursor-help"
                  :title="r.change.title"
                >{{ r.change.text }}</span>
                <span v-else class="text-ink-faint">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <template v-for="(pgn, idx) in paginationWindow(totalPages, page)" :key="idx">
        <span v-if="pgn === '...'" class="px-2 text-ink-faint">…</span>
        <button
          v-else
          class="w-10 h-10 rounded-pill font-medium text-sm"
          :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
          @click="goPage(pgn as number)"
        >{{ pgn }}</button>
      </template>
      <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>
  </div>
</template>
