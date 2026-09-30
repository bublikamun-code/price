<script setup lang="ts">
// Организации (менеджер): плотная таблица + вход в карточку, где живут
// реквизиты для счёта (SITEMAP §«/manager/organizations», §6 «Организации»).
// Коллекция — server-side q/sort/cursor (§6), а не клиентская выборка.
import type { OrganizationSummary } from '~/domain/api/v2/organizations.schema'
import { problemMessage } from '~/domain/api/v2/problem'
import { createOrganizationRepository } from '~/domain/organization/organization.repository'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Организации — Менеджер' })

const route = useRoute()
const router = useRouter()
const repository = createOrganizationRepository(useApiV2())

const loading = ref(true)
const error = ref('')
const organizations = ref<OrganizationSummary[]>([])
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const loadingMore = ref(false)

const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const appliedQ = ref(q.value.trim())

const SORTS = [
  { value: 'legalName', label: 'Название' },
  { value: '-legalName', label: 'Название ↓' },
  { value: 'createdAt', label: 'Создана ↑' },
  { value: '-createdAt', label: 'Создана ↓' },
] as const
const sort = ref<(typeof SORTS)[number]['value']>('legalName')

const LIMIT = 25

function organizationName(organization: OrganizationSummary): string {
  return organization.displayName || organization.legalName
}

async function load(reset = true) {
  if (reset) {
    loading.value = true
    error.value = ''
  } else {
    loadingMore.value = true
  }
  try {
    const page = await repository.list({
      q: appliedQ.value || undefined,
      sort: sort.value,
      limit: LIMIT,
      cursor: reset ? undefined : nextCursor.value ?? undefined,
    })
    organizations.value = reset ? page.organizations : [...organizations.value, ...page.organizations]
    nextCursor.value = page.nextCursor
    hasMore.value = page.hasMore
  } catch (cause) {
    error.value = problemMessage(cause, 'Не удалось загрузить организации')
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function applyFilters() {
  appliedQ.value = q.value.trim()
  void router.replace({ query: appliedQ.value ? { q: appliedQ.value } : {} })
  void load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Организации"
      title="Организации и коммерческие условия"
      description="Реквизиты для счёта на оплату правятся в карточке организации."
    />

    <div class="mb-4 flex flex-wrap items-end gap-3">
      <div>
        <label class="label" for="org-search">Поиск</label>
        <input
          id="org-search"
          v-model="q"
          type="search"
          class="input"
          placeholder="Название или УНП"
          data-testid="manager-organizations-search"
          @keyup.enter="applyFilters"
        >
      </div>
      <div>
        <label class="label" for="org-sort">Сортировка</label>
        <select id="org-sort" v-model="sort" class="input" @change="applyFilters">
          <option v-for="option in SORTS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      <button type="button" class="btn-primary min-h-11" data-testid="manager-organizations-apply" @click="applyFilters">
        Найти
      </button>
    </div>

    <div v-if="loading" class="space-y-2">
      <div class="skeleton h-10 w-full" />
      <div class="skeleton h-10 w-full" />
      <div class="skeleton h-10 w-full" />
    </div>

    <div v-else-if="error" class="border border-danger/50 bg-danger-soft p-5">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div><button class="btn-outline min-h-11" @click="load()">Повторить</button></div>
    </div>

    <div v-else-if="!organizations.length" class="border border-border bg-surface p-6 text-center">
      <p class="text-ink-muted mb-4">Организаций не найдено</p>
      <button v-if="appliedQ" class="btn-outline min-h-11" @click="q = ''; applyFilters()">
        Сбросить поиск
      </button>
    </div>

    <template v-else>
      <div class="border border-border bg-surface overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-5 py-3 font-medium">Организация</th>
              <th class="px-5 py-3 font-medium">УНП</th>
              <th class="px-5 py-3 font-medium">Валюта</th>
              <th class="px-5 py-3 font-medium">Статус</th>
              <th class="px-5 py-3 font-medium">Версия</th>
              <th class="px-5 py-3 font-medium" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="organization in organizations"
              :key="organization.id"
              class="border-t border-border"
              :data-testid="`manager-organization-row-${organization.id}`"
            >
              <td class="px-5 py-3">
                <p class="font-medium">{{ organizationName(organization) }}</p>
                <p v-if="organization.displayName" class="text-xs text-ink-faint">
                  {{ organization.legalName }}
                </p>
              </td>
              <td class="px-5 py-3 numeric">{{ organization.taxId || '—' }}</td>
              <td class="px-5 py-3">{{ organization.defaultCurrency }}</td>
              <td class="px-5 py-3">
                <UiStatusBadge
                  :tone="organization.isActive ? 'success' : 'neutral'"
                  :label="organization.isActive ? 'Активна' : 'Отключена'"
                />
              </td>
              <td class="px-5 py-3 numeric text-ink-muted">{{ organization.version }}</td>
              <td class="px-5 py-3 text-right">
                <NuxtLink
                  :to="`/manager/organizations/${organization.id}`"
                  class="btn-outline min-h-11"
                  :data-testid="`manager-organization-open-${organization.id}`"
                >
                  Открыть
                </NuxtLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="hasMore" class="mt-4">
        <button
          type="button"
          class="btn-outline min-h-11"
          :disabled="loadingMore"
          @click="load(false)"
        >
          {{ loadingMore ? 'Загрузка…' : 'Показать ещё' }}
        </button>
      </div>
    </template>
  </div>
</template>
