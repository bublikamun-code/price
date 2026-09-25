<script setup lang="ts">
// Клиенты (менеджер): список, поиск, создание с временным паролем. Этап 8.
// См. SITEMAP.md /manager/users, ARCHITECTURE_PLAN.md §6 (manager/users), §11 (RBAC).
import type { UserManagerCreateOut, UserManagerListItem, UserManagerPage } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Клиенты — Менеджер' })

const { request } = useApi()
/* закрытие модалки по клику на подложку — только если нажатие началось на ней (иначе срабатывает при выделении текста с уводом мыши) */
const overlayDown = ref(false)
const PER_PAGE = 20

const loading = ref(true)
const error = ref('')
const users = ref<UserManagerListItem[]>([])
const total = ref(0)
const page = ref(1)

// Поиск: q — поле ввода, appliedQ — применённое значение (сабмит по Enter/кнопке).
const q = ref('')
const appliedQ = ref('')

// Debounce поиска (300ms auto-search)
let searchTimer: ReturnType<typeof setTimeout> | null = null

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    applySearch()
  }, 300)
}

// Сортировка (клиентская)
const sortField = ref<'full_name' | 'company' | 'orders_count' | 'avg_discount_percent' | 'created_at'>('created_at')
const sortDir = ref<'asc' | 'desc'>('desc')

function toggleSort(field: typeof sortField.value) {
  if (sortField.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortDir.value = field === 'full_name' || field === 'company' ? 'asc' : 'desc'
  }
}

function sortIcon(field: string): string {
  if (sortField.value !== field) return 'heroicons:chevron-up-down'
  return sortDir.value === 'asc' ? 'heroicons:chevron-up' : 'heroicons:chevron-down'
}

const sortedUsers = computed(() => {
  const arr = [...users.value]
  const dir = sortDir.value === 'asc' ? 1 : -1
  return arr.sort((a, b) => {
    const f = sortField.value
    if (f === 'full_name' || f === 'company') {
      return dir * (a[f] ?? '').localeCompare(b[f] ?? '', 'ru')
    }
    if (f === 'orders_count') {
      return dir * ((a.orders_count ?? 0) - (b.orders_count ?? 0))
    }
    if (f === 'avg_discount_percent') {
      return dir * (Number(a.avg_discount_percent ?? 0) - Number(b.avg_discount_percent ?? 0))
    }
    // created_at
    return dir * (new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<UserManagerPage>('/api/v1/manager/users', {
      query: { q: appliedQ.value || undefined, page: page.value, per_page: PER_PAGE },
    })
    users.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить клиентов')
  } finally {
    loading.value = false
  }
}

function applySearch() {
  appliedQ.value = q.value.trim()
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

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU')
}

// --- Создание клиента ---
const showCreate = ref(false)
const createForm = reactive({
  email: '',
  full_name: '',
  company: '',
  phone: '',
  discount_percent_all: '',
})
const creating = ref(false)
const createError = ref('')
const tempPassword = ref('')

const createValid = computed(
  () => createForm.email.trim().length > 0 && createForm.full_name.trim().length > 0,
)

function openCreate() {
  createError.value = ''
  showCreate.value = true
}

function closeCreate() {
  showCreate.value = false
  createForm.email = ''
  createForm.full_name = ''
  createForm.company = ''
  createForm.phone = ''
  createForm.discount_percent_all = ''
}

async function submitCreate() {
  if (!createValid.value || creating.value) return
  createError.value = ''
  creating.value = true
  try {
    // 201 + {user, temp_password} — пароль показывается один раз.
    const res = await request<UserManagerCreateOut>('/api/v1/manager/users', {
      method: 'POST',
      body: {
        email: createForm.email.trim(),
        full_name: createForm.full_name.trim(),
        company: createForm.company.trim() || undefined,
        phone: createForm.phone.trim() || undefined,
        // v-model на type="number" возвращает число — .trim() там падает
        // (TypeError), из-за чего создание клиента со скидкой ломалось.
        discount_percent_all:
          String(createForm.discount_percent_all).trim() || undefined,
      },
    })
    closeCreate()
    page.value = 1
    await load()
    tempPassword.value = res.temp_password
  } catch (e) {
    if (getErrorStatus(e) === 409) createError.value = 'Клиент с таким email уже существует'
    else createError.value = getErrorMessage(e, 'Не удалось создать клиента')
  } finally {
    creating.value = false
  }
}

onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer) })

onMounted(load)
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Клиенты"
      :description="loading ? 'Загрузка…' : `${total} клиентов`"
    >
      <template #actions>
        <UiButton size="touch" @click="openCreate"><template #leading><Icon name="heroicons:plus" class="size-4" /></template>Создать клиента</UiButton>
      </template>
    </PageHeading>

    <!-- Поиск -->
    <form class="flex gap-2 mb-6 max-w-xl" @submit.prevent="applySearch">
      <div class="relative flex-1">
        <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
        <input
          v-model="q"
          type="search"
          aria-label="Поиск клиентов"
          placeholder="Поиск по имени, email, компании…"
          class="input pl-10"
          @input="onSearchInput"
        >
      </div>
      <button type="submit" class="btn-primary min-h-11 shrink-0">Найти</button>
    </form>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="border border-border bg-surface p-4">
      <div v-for="i in 6" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!sortedUsers.length" class="border border-border bg-surface p-6 text-ink-muted">
      <Icon name="heroicons:users" class="size-8 mb-3 text-ink-faint" />
      <p>{{ appliedQ ? 'По этому запросу клиентов нет' : 'Клиентов пока нет' }}</p>
    </div>

    <div v-else class="border border-border bg-surface">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th
                class="px-4 py-3 font-medium cursor-pointer select-none hover:text-ink"
                role="button"
                tabindex="0"
                :aria-sort="sortField === 'full_name' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
                @click="toggleSort('full_name')"
                @keydown.enter="toggleSort('full_name')"
                @keydown.space.prevent="toggleSort('full_name')"
              >
                <span class="inline-flex items-center gap-1">Клиент <Icon :name="sortIcon('full_name')" class="w-3.5 h-3.5" /></span>
              </th>
              <th class="px-4 py-3 font-medium">Email</th>
              <th class="px-4 py-3 font-medium">Телефон</th>
              <th
                class="px-4 py-3 font-medium text-right cursor-pointer select-none hover:text-ink"
                role="button"
                tabindex="0"
                :aria-sort="sortField === 'avg_discount_percent' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
                @click="toggleSort('avg_discount_percent')"
                @keydown.enter="toggleSort('avg_discount_percent')"
                @keydown.space.prevent="toggleSort('avg_discount_percent')"
              >
                <span class="inline-flex items-center justify-end gap-1">Скидка <Icon :name="sortIcon('avg_discount_percent')" class="w-3.5 h-3.5" /></span>
              </th>
              <th class="px-4 py-3 font-medium">Фикс. курс</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th
                class="px-4 py-3 font-medium text-right cursor-pointer select-none hover:text-ink"
                role="button"
                tabindex="0"
                :aria-sort="sortField === 'orders_count' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
                @click="toggleSort('orders_count')"
                @keydown.enter="toggleSort('orders_count')"
                @keydown.space.prevent="toggleSort('orders_count')"
              >
                <span class="inline-flex items-center justify-end gap-1">Заказов <Icon :name="sortIcon('orders_count')" class="w-3.5 h-3.5" /></span>
              </th>
              <th
                class="px-4 py-3 font-medium cursor-pointer select-none hover:text-ink"
                role="button"
                tabindex="0"
                :aria-sort="sortField === 'created_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
                @click="toggleSort('created_at')"
                @keydown.enter="toggleSort('created_at')"
                @keydown.space.prevent="toggleSort('created_at')"
              >
                <span class="inline-flex items-center gap-1">Создан <Icon :name="sortIcon('created_at')" class="w-3.5 h-3.5" /></span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="u in sortedUsers"
              :key="u.id"
              class="border-t border-border hover:bg-canvas/60 transition-colors duration-150 cursor-pointer"
              role="link"
              tabindex="0"
              :aria-label="`Открыть клиента ${u.full_name}`"
              @click="navigateTo(`/manager/users/${u.id}`)"
              @keydown.enter="navigateTo(`/manager/users/${u.id}`)"
              @keydown.space.prevent="navigateTo(`/manager/users/${u.id}`)"
            >
              <td class="px-4 py-3">
                <p class="font-medium">{{ u.full_name }}</p>
                <p v-if="u.company" class="text-xs text-ink-faint mt-0.5">{{ u.company }}</p>
              </td>
              <td class="px-4 py-3 text-ink-muted">{{ u.email }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ u.phone || '—' }}</td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <template v-if="u.avg_discount_percent !== null">{{ formatPercent(u.avg_discount_percent) }}</template>
                <template v-else><span class="text-ink-faint">—</span></template>
              </td>
              <td class="px-4 py-3 text-ink-muted">{{ u.fixed_rate_currency || '—' }}</td>
              <td class="px-4 py-3">
                <span v-if="u.is_active" class="badge-success">Активен</span>
                <span v-else class="badge-danger">Заблокирован</span>
              </td>
              <td class="px-4 py-3 text-right">{{ u.orders_count }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(u.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button class="btn-ghost size-11" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <template v-for="(pgn, idx) in paginationWindow(totalPages, page)" :key="idx">
        <span v-if="pgn === '...'" class="px-2 text-ink-faint">…</span>
        <button
          v-else
          class="btn-outline size-11 font-medium text-sm"
          :class="pgn === page ? 'border-action bg-action text-white' : 'text-ink-muted hover:bg-surface-2'"
          @click="goPage(pgn as number)"
        >{{ pgn }}</button>
      </template>
      <button class="btn-ghost size-11" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>

    <!-- Создание клиента -->
    <div
      v-if="showCreate"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) closeCreate(); overlayDown = false"
    >
      <form class="max-h-[90vh] w-full max-w-lg overflow-y-auto border border-border-strong bg-surface p-5" @submit.prevent="submitCreate">
        <div class="flex items-start justify-between gap-4 mb-5">
          <h3 class="font-semibold">Новый клиент</h3>
          <button type="button" class="btn-ghost -mr-2 size-11 shrink-0" @click="closeCreate">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label" for="cu-email">Email <span class="text-danger">*</span></label>
            <input id="cu-email" v-model="createForm.email" type="email" class="input" placeholder="client@example.com" required>
          </div>
          <div>
            <label class="label" for="cu-name">ФИО <span class="text-danger">*</span></label>
            <input id="cu-name" v-model="createForm.full_name" type="text" class="input" placeholder="Иванов Иван" required>
          </div>
          <div>
            <label class="label" for="cu-company">Компания</label>
            <input id="cu-company" v-model="createForm.company" type="text" class="input" placeholder="ООО «Пример»">
            <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
          </div>
          <div>
            <label class="label" for="cu-phone">Телефон</label>
            <input id="cu-phone" v-model="createForm.phone" type="tel" class="input" placeholder="+375 29 000-00-00">
            <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
          </div>
          <div>
            <label class="label" for="cu-discount">Начальная скидка %</label>
            <input
              id="cu-discount"
              v-model="createForm.discount_percent_all"
              type="number"
              min="0"
              max="100"
              step="0.5"
              class="input"
              placeholder="Напр. 5"
            >
            <p class="text-xs text-ink-faint mt-1.5">Применяется ко всем брендам. Необязательно.</p>
          </div>
        </div>

        <div v-if="createError" class="badge-danger w-full justify-center py-2 mt-5">{{ createError }}</div>

        <div class="flex justify-end gap-2 mt-6">
          <button type="button" class="btn-ghost min-h-11" @click="closeCreate">Отмена</button>
          <button type="submit" class="btn-primary min-h-11" :disabled="!createValid || creating">
            <span v-if="creating" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"/>
            {{ creating ? 'Создание…' : 'Создать' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Временный пароль после создания -->
    <TempPasswordDialog v-if="tempPassword" :password="tempPassword" @close="tempPassword = ''"/>
  </div>
</template>
