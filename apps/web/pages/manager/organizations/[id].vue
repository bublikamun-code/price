<script setup lang="ts">
// Карточка организации (менеджер): SITEMAP §«/manager/organizations/[id]».
// Реализован блок «Реквизиты для счёта» (§6 «Счета на оплату», §16 п.40 п.4):
// УНП, юридический адрес, юр. телефон/email, банк (наименование/код/счёт).
// Сохранение — PATCH /api/v2/manager/organizations/{id} с `If-Match` по версии
// организации; 409 STALE_RESOURCE_VERSION не перетирает правки молча, а
// предлагает перечитать карточку (§6 «Concurrency»).
import type { OrganizationDetail } from '~/domain/api/v2/organizations.schema'
import { problemMessage, toAppProblem } from '~/domain/api/v2/problem'
import { createOrganizationRepository } from '~/domain/organization/organization.repository'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })

const route = useRoute()
const organizations = createOrganizationRepository(useApiV2())
const invoices = useInvoiceRepository()

const organizationId = computed(() => {
  const raw = route.params.id
  return Array.isArray(raw) ? raw[0] : raw
})

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const organization = ref<OrganizationDetail | null>(null)

const saving = ref(false)
const saveError = ref('')
const savedAt = ref(false)
const stale = ref(false)

/** Черновик формы реквизитов: пустая строка = поле не заполнено (прочерк в PDF). */
interface RequisitesForm {
  taxId: string
  legalAddress: string
  legalPhone: string
  legalEmail: string
  bankName: string
  bankCode: string
  bankAccount: string
}

const form = reactive<RequisitesForm>({
  taxId: '',
  legalAddress: '',
  legalPhone: '',
  legalEmail: '',
  bankName: '',
  bankCode: '',
  bankAccount: '',
})

useHead({
  title: computed(() =>
    organization.value ? `${organization.value.legalName} — Организация` : 'Организация',
  ),
})

function fillForm(source: OrganizationDetail) {
  form.taxId = source.taxId ?? ''
  form.legalAddress = source.legalAddress ?? ''
  form.legalPhone = source.legalPhone ?? ''
  form.legalEmail = source.legalEmail ?? ''
  form.bankName = source.bankName ?? ''
  form.bankCode = source.bankCode ?? ''
  form.bankAccount = source.bankAccount ?? ''
}

/** Пустое поле отправляем null — организация может жить без реквизитов. */
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function organizationName(value: OrganizationDetail): string {
  return value.displayName || value.legalName
}

async function load() {
  if (!organizationId.value) {
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  notFound.value = false
  stale.value = false
  try {
    const snapshot = await organizations.getById(organizationId.value)
    organization.value = snapshot.organization
    fillForm(snapshot.organization)
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось загрузить организацию')
    if (problem.status === 404) notFound.value = true
    else error.value = problemMessage(cause, 'Не удалось загрузить организацию')
  } finally {
    loading.value = false
  }
}

const dirty = computed(() => {
  if (!organization.value) return false
  return (
    form.taxId !== (organization.value.taxId ?? '') ||
    form.legalAddress !== (organization.value.legalAddress ?? '') ||
    form.legalPhone !== (organization.value.legalPhone ?? '') ||
    form.legalEmail !== (organization.value.legalEmail ?? '') ||
    form.bankName !== (organization.value.bankName ?? '') ||
    form.bankCode !== (organization.value.bankCode ?? '') ||
    form.bankAccount !== (organization.value.bankAccount ?? '')
  )
})

async function save() {
  if (!organization.value || saving.value) return
  const current = organization.value
  saving.value = true
  saveError.value = ''
  savedAt.value = false
  stale.value = false
  try {
    const updated = await invoices.updateOrganizationRequisites(
      current.id,
      {
        taxId: orNull(form.taxId),
        legalAddress: orNull(form.legalAddress),
        legalPhone: orNull(form.legalPhone),
        legalEmail: orNull(form.legalEmail),
        bankName: orNull(form.bankName),
        bankCode: orNull(form.bankCode),
        bankAccount: orNull(form.bankAccount),
        version: current.version,
      },
      current.version,
    )
    organization.value = updated
    fillForm(updated)
    savedAt.value = true
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось сохранить реквизиты')
    if (problem.code === 'STALE_RESOURCE_VERSION') {
      // Реквизиты общие для всех счетов организации: конкурируют правки
      // менеджеров. Молча перетирать нельзя — предлагаем перечитать.
      stale.value = true
      saveError.value = `${problem.message}. Реквизиты уже изменены — перечитайте карточку.`
    } else {
      saveError.value = problemMessage(cause, 'Не удалось сохранить реквизиты')
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <nav class="flex items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/manager/organizations" class="hover:text-primary">Организации</NuxtLink>
      <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
      <span class="text-ink">Карточка</span>
    </nav>

    <div v-if="loading" class="space-y-4">
      <div class="skeleton h-24 w-full" />
      <div class="skeleton h-64 w-full" />
    </div>

    <div v-else-if="notFound" class="border border-border bg-surface p-6 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="size-8 mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Организация не найдена</p>
      <NuxtLink to="/manager/organizations" class="btn-primary">К списку организаций</NuxtLink>
    </div>

    <div v-else-if="error && !organization" class="border border-danger/50 bg-danger-soft p-5">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div><button class="btn-outline min-h-11" @click="load">Повторить</button></div>
    </div>

    <div v-else-if="organization">
      <PageHeading
        eyebrow="Организации"
        :title="organizationName(organization)"
        :description="`${organization.legalName} · ${organization.countryCode} · версия ${organization.version}`"
      >
        <template #actions>
          <UiStatusBadge
            :tone="organization.isActive ? 'success' : 'neutral'"
            :label="organization.isActive ? 'Активна' : 'Отключена'"
            dot
          />
        </template>
      </PageHeading>

      <!-- Сводка -->
      <div class="mb-5 grid gap-6 sm:grid-cols-2">
        <div class="border border-border bg-surface p-4">
          <h3 class="font-semibold mb-3">Организация</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридическое лицо</span>
            <span class="font-medium text-right">{{ organization.legalName }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">УНП</span>
            <span class="numeric font-medium">{{ organization.taxId || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Валюта</span>
            <span class="font-medium">{{ organization.defaultCurrency }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Создана</span>
            <span class="font-medium">{{ formatDateTime(organization.createdAt) }}</span>
          </div>
        </div>
        <div class="border border-border bg-surface p-4">
          <h3 class="font-semibold mb-3">Контакты</h3>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический телефон</span>
            <span class="font-medium">{{ organization.legalPhone || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический email</span>
            <span class="font-medium">{{ organization.legalEmail || '—' }}</span>
          </div>
          <div class="flex justify-between text-sm py-1">
            <span class="text-ink-muted">Юридический адрес</span>
            <span class="text-right font-medium">{{ organization.legalAddress || '—' }}</span>
          </div>
        </div>
      </div>

      <!-- Реквизиты для счёта -->
      <div class="mb-5 border border-border bg-surface p-4" data-testid="manager-organization-requisites">
        <h3 class="font-semibold mb-1">Реквизиты для счёта</h3>
        <p class="mb-3 text-xs text-ink-faint">
          Печатаются в PDF счёта на оплату. Незаполненные поля выводятся прочерком.
          Правка попадает в следующий перерендер PDF.
        </p>

        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="label" for="org-tax-id">УНП</label>
            <input id="org-tax-id" v-model="form.taxId" class="input" data-testid="manager-org-tax-id">
          </div>
          <div>
            <label class="label" for="org-legal-phone">Юридический телефон</label>
            <input id="org-legal-phone" v-model="form.legalPhone" class="input" data-testid="manager-org-legal-phone">
          </div>
          <div>
            <label class="label" for="org-legal-email">Юридический email</label>
            <input id="org-legal-email" v-model="form.legalEmail" type="email" class="input" data-testid="manager-org-legal-email">
          </div>
          <div>
            <label class="label" for="org-bank-name">Банк</label>
            <input id="org-bank-name" v-model="form.bankName" class="input" data-testid="manager-org-bank-name">
          </div>
          <div>
            <label class="label" for="org-bank-code">Код банка</label>
            <input id="org-bank-code" v-model="form.bankCode" class="input numeric" data-testid="manager-org-bank-code">
          </div>
          <div>
            <label class="label" for="org-bank-account">Расчётный счёт</label>
            <input id="org-bank-account" v-model="form.bankAccount" class="input numeric" data-testid="manager-org-bank-account">
          </div>
          <div class="sm:col-span-2">
            <label class="label" for="org-legal-address">Юридический адрес</label>
            <textarea
              id="org-legal-address"
              v-model="form.legalAddress"
              rows="2"
              class="input"
              data-testid="manager-org-legal-address"
            />
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="btn-primary min-h-11"
            :disabled="saving || !dirty"
            data-testid="manager-org-requisites-save"
            @click="save"
          >
            <span
              v-if="saving"
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"
            />
            <Icon v-else name="heroicons:check" class="w-4 h-4" />
            {{ saving ? 'Сохраняем…' : 'Сохранить реквизиты' }}
          </button>
          <span v-if="savedAt && !saveError" class="badge-success" data-testid="manager-org-requisites-saved">
            Реквизиты сохранены
          </span>
          <p class="text-xs text-ink-faint">
            Версия {{ organization.version }} сверяется при сохранении.
          </p>
        </div>

        <p v-if="saveError" class="badge-danger mt-3" role="alert" data-testid="manager-org-requisites-error">
          {{ saveError }}
        </p>
        <button
          v-if="stale"
          type="button"
          class="btn-outline mt-2 min-h-11"
          data-testid="manager-org-requisites-reload"
          @click="load"
        >
          Перечитать реквизиты
        </button>
      </div>
    </div>
  </div>
</template>
