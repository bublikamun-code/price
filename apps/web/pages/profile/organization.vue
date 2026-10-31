<script setup lang="ts">
import type { OrganizationApprovalMode } from '~/types/api'
import { organizationDetailResponseSchema, type OrganizationDetail } from '~/domain/api/v2/organizations.schema'
import { AppProblem } from '~/domain/api/v2/problem'

definePageMeta({
  layout: 'client',
  middleware: ['auth', 'role'],
  roles: ['CLIENT'],
})

useHead({ title: 'Организация' })

const { store, ensureLoaded, refresh } = useSessionContext()

const activeOrganization = computed(() => {
  const context = store.context
  if (!context?.organizationId) return null
  return context.memberships.find((membership) => membership.organizationId === context.organizationId) ?? null
})

const roleLabels: Record<string, string> = {
  OWNER: 'Владелец',
  ADMIN: 'Администратор',
  MANAGER: 'Менеджер',
  MEMBER: 'Участник',
  VIEWER: 'Наблюдатель',
}
const statusLabels: Record<string, string> = {
  ACTIVE: 'Активно',
  INVITED: 'Приглашён',
  SUSPENDED: 'Приостановлено',
}

function roleLabel(value: string): string {
  return roleLabels[value] ?? value
}

function statusLabel(value: string): string {
  return statusLabels[value] ?? value
}

// ---------- Согласование заявок (Э6): настройки видит и меняет только OWNER ----------
const api = useApiV2()

// UiSelect работает со string | number — держим строку и приводим при сохранении.
const approvalMode = ref<string>('OFF')
const approvalLimitInput = ref('')
const approvalLoading = ref(false)
const approvalSaving = ref(false)
const approvalError = ref('')
const approvalSaved = ref(false)
const approvalLimitError = ref('')
const approvalLimitPlaceholder = ref('0.00')

const isOrganizationOwner = computed(
  () => activeOrganization.value?.role === 'OWNER' && activeOrganization.value?.status === 'ACTIVE',
)

const APPROVAL_MODE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'OFF', label: 'Без согласования' },
  { value: 'ALL', label: 'Все заявки' },
  { value: 'OVER_LIMIT', label: 'Заявки сверх лимита' },
]

const APPROVAL_MODE_HINTS: Record<string, string> = {
  OFF: 'Заявки уходят менеджеру сразу, без визы владельца.',
  ALL: 'Каждую заявку перед обработкой подтверждает владелец организации.',
  OVER_LIMIT: 'Заявки с суммой выше лимита требуют визы владельца организации.',
}

function approvalHint(mode: string): string {
  return APPROVAL_MODE_HINTS[mode] ?? ''
}

function problemMessage(cause: unknown, fallback: string): string {
  return cause instanceof AppProblem ? cause.message : getErrorMessage(cause, fallback)
}

function applyOrganization(organization: OrganizationDetail) {
  approvalMode.value = organization.approvalMode ?? 'OFF'
  // Decimal может приходить строкой — для поля ввода приводим через Number().
  const limit = organization.approvalLimitAmount
  const numeric = limit === null || limit === undefined ? null : Number(limit)
  approvalLimitInput.value = numeric !== null && Number.isFinite(numeric) ? String(numeric) : ''
  approvalLimitPlaceholder.value = numeric !== null && Number.isFinite(numeric) && numeric > 0 ? String(numeric) : '0.00'
}

async function loadApproval() {
  const organizationId = store.context?.organizationId
  if (!organizationId) return
  approvalLoading.value = true
  approvalError.value = ''
  try {
    const envelope = await api.get(`/api/v2/organizations/${organizationId}`, organizationDetailResponseSchema)
    applyOrganization(envelope.data)
  } catch (cause) {
    approvalError.value = problemMessage(cause, 'Не удалось загрузить настройки согласования')
  } finally {
    approvalLoading.value = false
  }
}

function normalizedLimit(): string | null {
  const raw = approvalLimitInput.value.trim()
  if (!raw) return null
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) return null
  return raw
}

async function saveApproval() {
  const organizationId = store.context?.organizationId
  if (!organizationId || approvalSaving.value) return
  approvalLimitError.value = ''
  approvalSaved.value = false
  const limit = normalizedLimit()
  if (approvalMode.value === 'OVER_LIMIT' && !limit) {
    approvalLimitError.value = 'Укажите положительную сумму лимита'
    return
  }
  approvalSaving.value = true
  try {
    const envelope = await api.execute(
      `/api/v2/organizations/${organizationId}/approval`,
      organizationDetailResponseSchema,
      {
        method: 'PATCH',
        body: {
          approvalMode: approvalMode.value as OrganizationApprovalMode,
          // Лимит уходим только в режиме OVER_LIMIT; Decimal передаём строкой.
          ...(approvalMode.value === 'OVER_LIMIT' && limit ? { approvalLimitAmount: limit } : {}),
        },
      },
    )
    applyOrganization(envelope.data.data)
    approvalSaved.value = true
  } catch (cause) {
    // 403 (не OWNER) и 422 (валидация) — текстом в секции.
    approvalError.value = problemMessage(cause, 'Не удалось сохранить настройки согласования')
  } finally {
    approvalSaving.value = false
  }
}

watch(
  () => [store.context?.organizationId, isOrganizationOwner.value] as const,
  ([organizationId, owner]) => {
    approvalSaved.value = false
    approvalError.value = ''
    if (organizationId && owner) void loadApproval()
  },
  { immediate: true },
)

async function load() {
  try {
    await ensureLoaded()
  } catch {
    // The store exposes the normalized problem to the template.
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="mx-auto max-w-5xl">
    <nav class="mb-6 flex items-center gap-2 text-sm text-ink-muted" aria-label="Хлебные крошки">
      <NuxtLink to="/profile" class="hover:text-action">Профиль</NuxtLink>
      <Icon name="heroicons:chevron-right" class="size-4 text-ink-muted" aria-hidden="true" />
      <span class="text-ink" aria-current="page">Организация</span>
    </nav>

    <PageHeading
      eyebrow="Коммерческий контекст"
      title="Организация"
      description="Организация определяет корпоративные цены, состав заявок и доступ пользователей."
    />

    <div v-if="store.error" class="border-b border-danger/40 py-5" role="alert">
      <p class="font-semibold text-danger-text">{{ store.error.message }}</p>
      <p v-if="store.error.requestId" class="mt-1 font-mono text-sm text-ink-muted">Request ID: {{ store.error.requestId }}</p>
      <button type="button" class="btn-outline mt-4" @click="refresh">Повторить</button>
    </div>

    <div v-if="store.loading" class="divide-y divide-border border-b border-border" aria-busy="true" aria-label="Загрузка организации">
      <div v-for="index in 4" :key="index" class="grid gap-3 py-4 md:grid-cols-[14rem_minmax(0,1fr)]">
        <div class="skeleton h-5 w-28" />
        <div class="skeleton h-5 w-full max-w-md" />
      </div>
    </div>

    <template v-else-if="store.context">
      <section class="grid border-b border-border py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="scope-heading">
        <h2 id="scope-heading" class="text-sm font-bold text-ink">Текущий контекст</h2>
        <dl class="divide-y divide-border">
          <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Коммерческая база</dt>
            <dd class="font-semibold text-ink">
              {{ store.context.commercialScope === 'ORGANIZATION' ? 'Организация' : 'Пользователь' }}
            </dd>
          </div>
          <div class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Активная организация</dt>
            <dd class="font-semibold text-ink">
              {{ activeOrganization?.legalName || (store.context.organizationId ? store.context.organizationId : 'Не выбрана') }}
            </dd>
          </div>
          <div v-if="!store.context.organizationId" class="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
            <dt class="text-sm text-ink-muted">Режим</dt>
            <dd class="text-ink-muted">Заявки и цены используют пользовательский коммерческий контекст.</dd>
          </div>
        </dl>
      </section>

      <section class="border-b border-border py-6" aria-labelledby="memberships-heading">
        <div class="grid gap-2 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8">
          <div>
            <h2 id="memberships-heading" class="text-sm font-bold text-ink">Доступные организации</h2>
            <p class="mt-2 text-sm text-ink-muted">У каждой организации собственные условия и участники.</p>
          </div>

          <div v-if="store.context.memberships.length" class="divide-y divide-border border-y border-border">
            <article
              v-for="membership in store.context.memberships"
              :key="membership.organizationId"
              class="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
            >
              <div class="min-w-0">
                <h3 class="font-semibold text-ink">{{ membership.displayName || membership.legalName }}</h3>
                <p class="mt-1 text-sm text-ink-muted">{{ membership.legalName }}</p>
                <p class="mt-1 font-mono text-xs text-ink-muted">{{ membership.organizationId }}</p>
              </div>
              <dl class="flex flex-wrap gap-x-5 gap-y-2 text-sm sm:justify-end">
                <div class="flex gap-2">
                  <dt class="text-ink-muted">Роль</dt>
                  <dd class="font-semibold text-ink">{{ roleLabel(membership.role) }}</dd>
                </div>
                <div class="flex gap-2">
                  <dt class="text-ink-muted">Статус</dt>
                  <dd class="font-semibold text-ink">{{ statusLabel(membership.status) }}</dd>
                </div>
                <div v-if="membership.organizationId === store.context.organizationId" class="flex gap-2">
                  <dt class="sr-only">Текущий выбор</dt>
                  <dd><span class="badge-success">Активна</span></dd>
                </div>
              </dl>
            </article>
          </div>
          <p v-else class="border-y border-border py-6 text-ink-muted">У пользователя нет активных memberships.</p>
        </div>
      </section>

      <!-- Согласование заявок (Э6): настройки доступны только владельцу организации -->
      <section
        v-if="isOrganizationOwner"
        class="border-b border-border py-6"
        aria-labelledby="approval-heading"
        data-testid="org-approval-settings"
      >
        <div class="grid gap-2 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8">
          <div>
            <h2 id="approval-heading" class="text-sm font-bold text-ink">Согласование заявок</h2>
            <p class="mt-2 text-sm text-ink-muted">Виза владельца до передачи заявки менеджеру.</p>
          </div>

          <div v-if="approvalLoading" class="border-y border-border py-6" aria-busy="true" aria-label="Загрузка настроек согласования">
            <div class="skeleton h-10 w-full max-w-md" />
          </div>

          <template v-else>
            <div v-if="approvalError" class="border border-danger/40 bg-danger-soft p-3" role="alert">
              <p class="text-sm text-danger-text">{{ approvalError }}</p>
              <button type="button" class="btn-outline mt-3" @click="loadApproval">Повторить</button>
            </div>

            <form v-else class="flex max-w-md flex-col gap-4" @submit.prevent="saveApproval">
              <UiSelect
                v-model="approvalMode"
                :options="APPROVAL_MODE_OPTIONS"
                label="Режим согласования"
                data-testid="org-approval-mode"
              />
              <p class="-mt-2 text-xs leading-5 text-ink-muted" data-testid="org-approval-hint">{{ approvalHint(approvalMode) }}</p>

              <UiField
                v-if="approvalMode === 'OVER_LIMIT'"
                for="org-approval-limit"
                label="Лимит суммы заявки, BYN"
                description="Заявки дороже лимита потребуют визы владельца"
                :error="approvalLimitError"
              >
                <input
                  id="org-approval-limit"
                  v-model="approvalLimitInput"
                  type="number"
                  min="0.01"
                  step="0.01"
                  inputmode="decimal"
                  :placeholder="approvalLimitPlaceholder"
                  class="numeric block min-h-11 w-full border bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus lg:min-h-9"
                  :class="approvalLimitError ? 'border-danger' : 'border-border-strong'"
                  data-testid="org-approval-limit"
                >
              </UiField>

              <p v-if="approvalSaved" class="text-sm font-medium text-success-text" role="status" data-testid="org-approval-saved">Настройки сохранены</p>

              <div>
                <UiButton type="submit" size="touch" :loading="approvalSaving" :disabled="approvalSaving" data-testid="org-approval-save">Сохранить</UiButton>
              </div>
            </form>
          </template>
        </div>
      </section>

      <section v-if="store.context.user.legacyCompany" class="grid py-6 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-8" aria-labelledby="legacy-heading">
        <h2 id="legacy-heading" class="text-sm font-bold text-ink">Прежнее поле</h2>
        <div>
          <p class="font-semibold text-ink">{{ store.context.user.legacyCompany }}</p>
          <p class="mt-1 text-sm text-ink-muted">Название из legacy-профиля не заменяет membership и не используется как организация.</p>
        </div>
      </section>
    </template>
  </div>
</template>
