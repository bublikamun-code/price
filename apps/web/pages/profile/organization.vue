<script setup lang="ts">
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
