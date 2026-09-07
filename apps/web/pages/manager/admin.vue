<script setup lang="ts">
// Админ-кабинет: создание менеджеров с временным паролем, блокировка/разблокировка.
// GET/POST /api/v1/admin/managers, PATCH /api/v1/admin/managers/{id} (§6, RBAC §11).
import type { AdminManagerCreateOut, AdminManagerListItem } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['ADMIN'] })
useHead({ title: 'Администрирование — Менеджер' })

const { request } = useApi()
/* закрытие модалки по клику на подложку — только если нажатие началось на ней (иначе срабатывает при выделении текста с уводом мыши) */
const overlayDown = ref(false)

const loading = ref(true)
const error = ref('')
const managers = ref<AdminManagerListItem[]>([])

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    managers.value = await request<AdminManagerListItem[]>('/api/v1/admin/managers')
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить менеджеров')
  } finally {
    loading.value = false
  }
}

// --- Создание менеджера ---
const showCreate = ref(false)
const createForm = reactive({ email: '', full_name: '', phone: '' })
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
  createForm.phone = ''
}

async function submitCreate() {
  if (!createValid.value || creating.value) return
  createError.value = ''
  creating.value = true
  try {
    // 201 + {user, temp_password} — пароль показывается один раз.
    const res = await request<AdminManagerCreateOut>('/api/v1/admin/managers', {
      method: 'POST',
      body: {
        email: createForm.email.trim(),
        full_name: createForm.full_name.trim(),
        phone: createForm.phone.trim() || undefined,
      },
    })
    closeCreate()
    await load()
    tempPassword.value = res.temp_password
  } catch (e) {
    if (getErrorStatus(e) === 409) createError.value = 'Менеджер с таким email уже существует'
    else createError.value = getErrorMessage(e, 'Не удалось создать менеджера')
  } finally {
    creating.value = false
  }
}

// --- Блокировка / разблокировка ---
const togglingId = ref<string | null>(null)
const confirmTarget = ref<AdminManagerListItem | null>(null)
const actionError = ref('')

function askToggle(m: AdminManagerListItem) {
  actionError.value = ''
  confirmTarget.value = m
}

function cancelToggle() {
  confirmTarget.value = null
}

async function confirmToggle() {
  const target = confirmTarget.value
  if (!target || togglingId.value) return
  togglingId.value = target.id
  actionError.value = ''
  try {
    await request(`/api/v1/admin/managers/${target.id}`, {
      method: 'PATCH',
      body: { is_active: !target.is_active },
    })
    managers.value = managers.value.map(m =>
      m.id === target.id ? { ...m, is_active: !target.is_active } : m,
    )
    confirmTarget.value = null
  } catch (e) {
    actionError.value = getErrorMessage(e, 'Не удалось изменить статус')
  } finally {
    togglingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex items-center justify-between gap-4 mb-6">
      <h1 class="text-2xl font-bold">Администрирование</h1>
      <button type="button" class="btn-primary" @click="openCreate">
        <Icon name="heroicons:plus" class="w-5 h-5" />
        <span>Создать менеджера</span>
      </button>
    </div>

    <div v-if="error" class="badge-danger w-full justify-center py-2 mb-4">{{ error }}</div>
    <div v-if="actionError" class="badge-danger w-full justify-center py-2 mb-4">{{ actionError }}</div>

    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-ink-faint border-b border-border">
            <th class="px-4 py-3 font-medium">Имя</th>
            <th class="px-4 py-3 font-medium">Email</th>
            <th class="px-4 py-3 font-medium">Статус</th>
            <th class="px-4 py-3 font-medium">Создан</th>
            <th class="px-4 py-3 font-medium text-right">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="px-4 py-8 text-center text-ink-faint">Загрузка…</td>
          </tr>
          <tr v-else-if="managers.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-ink-faint">Менеджеров пока нет</td>
          </tr>
          <tr v-for="m in managers" :key="m.id" class="border-b border-border last:border-b-0">
            <td class="px-4 py-3 font-medium">{{ m.full_name }}</td>
            <td class="px-4 py-3">{{ m.email }}</td>
            <td class="px-4 py-3">
              <span v-if="m.is_active" class="badge-success">Активен</span>
              <span v-else class="badge-danger">Заблокирован</span>
            </td>
            <td class="px-4 py-3">{{ formatDate(m.created_at) }}</td>
            <td class="px-4 py-3 text-right whitespace-nowrap">
              <button
                type="button"
                class="btn-ghost text-sm"
                :disabled="togglingId === m.id"
                @click="askToggle(m)"
              >{{ m.is_active ? 'Блокировать' : 'Разблокировать' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Создание менеджера -->
    <div
      v-if="showCreate"
      class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) closeCreate(); overlayDown = false"
    >
      <form class="card max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto scrollbar-none" @submit.prevent="submitCreate">
        <div class="flex items-start justify-between gap-4 mb-5">
          <h3 class="font-semibold">Новый менеджер</h3>
          <button type="button" class="btn-ghost p-2 -mr-2 shrink-0" @click="closeCreate">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label" for="am-email">Email <span class="text-danger">*</span></label>
            <input id="am-email" v-model="createForm.email" type="email" class="input" placeholder="manager@example.com" required>
          </div>
          <div>
            <label class="label" for="am-name">ФИО <span class="text-danger">*</span></label>
            <input id="am-name" v-model="createForm.full_name" type="text" class="input" placeholder="Иванов Иван" required>
          </div>
          <div>
            <label class="label" for="am-phone">Телефон</label>
            <input id="am-phone" v-model="createForm.phone" type="tel" class="input" placeholder="+375 29 000-00-00">
            <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
          </div>
        </div>

        <div v-if="createError" class="badge-danger w-full justify-center py-2 mt-5">{{ createError }}</div>

        <div class="flex justify-end gap-2 mt-6">
          <button type="button" class="btn-ghost" @click="closeCreate">Отмена</button>
          <button type="submit" class="btn-primary" :disabled="!createValid || creating">
            {{ creating ? 'Создание…' : 'Создать' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Подтверждение блокировки / разблокировки -->
    <div
      v-if="confirmTarget"
      class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) cancelToggle(); overlayDown = false"
    >
      <div class="card max-w-md w-full p-6">
        <h3 class="font-semibold mb-3">{{ confirmTarget.is_active ? 'Заблокировать менеджера?' : 'Разблокировать менеджера?' }}</h3>
        <p class="text-sm text-ink-muted mb-2">{{ confirmTarget.full_name }} ({{ confirmTarget.email }})</p>
        <p v-if="confirmTarget.is_active" class="text-sm text-ink-faint mb-5">
          Активные сессии будут завершены немедленно.
        </p>
        <div v-else class="mb-5" />
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="cancelToggle">Отмена</button>
          <button type="button" class="btn-primary" :disabled="togglingId !== null" @click="confirmToggle">
            {{ togglingId !== null ? 'Сохранение…' : 'Подтвердить' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Временный пароль после создания -->
    <TempPasswordDialog v-if="tempPassword" :password="tempPassword" @close="tempPassword = ''"/>
  </div>
</template>
