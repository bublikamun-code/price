<script setup lang="ts">
// Панель скидок за объём бренда (этап 5 роадмапа, §6, §16 п.41).
//
// Лестница «от N шт — X%» на бренд, а не на товар: ступень одна для всех
// позиций бренда, а применяется к количеству **строки** заказа. Отсюда
// форма: список ступеней по возрастанию порога, добавление новой, правка
// существующей и удаление с подтверждением.
//
// Правка и удаление идут с `If-Match` по `version` **ступени** (§16 п.41
// п.8) — общая версия бренда заставила бы менеджера перезагружать чужую
// правку процента. 409 STALE_RESOURCE_VERSION означает «кто-то уже правил»:
// перечитываем лестницу и просим повторить, а не молча перетираем.
//
// Внутри формы товара панели <form> быть не может (вложенные формы ломают
// SSR) — сабмит по кнопке type="button", как в ProductDocumentsPanel.
import type { VolumeTier } from '~/domain/api/v2/volume_tiers.schema'
import { createVolumeTiersRepository } from '~/domain/volume_tiers/volume_tiers.repository'
import { problemMessage, toAppProblem } from '~/domain/api/v2/problem'

const props = defineProps<{
  brandId: string
  brandName?: string
}>()

const repository = createVolumeTiersRepository(useApiV2())

const loading = ref(false)
const loadError = ref('')
const tiers = ref<VolumeTier[]>([])

// Форма добавления: новый порог задаётся целиком.
const newMinQty = ref<number | null>(null)
const newPercent = ref<string>('')
const creating = ref(false)
const createError = ref('')

// Форма правки: оба поля опциональны (PATCH), пустое = не менять.
const editingId = ref<string | null>(null)
const editMinQty = ref<number | null>(null)
const editPercent = ref<string>('')
const saving = ref(false)
const saveError = ref('')

const confirmingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const deleteError = ref<{ id: string; msg: string } | null>(null)

/** «10» → 10, «10,5» → 10.5; пустое/мусор → null. */
function parseNumber(raw: string | number | null): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null
  const text = (raw ?? '').trim().replace(',', '.')
  if (!text) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

const canCreate = computed(
  () =>
    newMinQty.value != null &&
    newMinQty.value >= 1 &&
    parseNumber(newPercent.value) != null &&
    parseNumber(newPercent.value)! > 0 &&
    parseNumber(newPercent.value)! < 100,
)

/** Подсказка «следующая ступень начинается с 50 шт» — про пороги, не про цены. */
const nextThresholdHint = computed(() => {
  if (tiers.value.length < 2) return ''
  const sorted = [...tiers.value].sort((a, b) => a.minQty - b.minQty)
  const last = sorted[sorted.length - 1]
  if (!last) return ''
  return `Последняя ступень действует от ${last.minQty} шт и выше.`
})

async function load() {
  if (!props.brandId) return
  loading.value = true
  loadError.value = ''
  try {
    tiers.value = await repository.list(props.brandId)
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось загрузить скидки за объём')
    loadError.value = problemMessage(problem, 'Не удалось загрузить скидки за объём')
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  const minQty = newMinQty.value
  const percent = parseNumber(newPercent.value)
  if (creating.value || minQty == null || percent == null) return
  creating.value = true
  createError.value = ''
  try {
    const created = await repository.create(props.brandId, { minQty, discountPercent: percent })
    // Сервер отдаёт лестницу по возрастанию порога — держим тот же порядок.
    tiers.value = [...tiers.value, created].sort((a, b) => a.minQty - b.minQty)
    newMinQty.value = null
    newPercent.value = ''
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось добавить ступень')
    createError.value =
      problem.code === 'VOLUME_TIER_DUPLICATE_THRESHOLD'
        ? `Порог от ${minQty} шт уже занят`
        : problemMessage(problem, 'Не удалось добавить ступень')
  } finally {
    creating.value = false
  }
}

function startEdit(tier: VolumeTier) {
  editingId.value = tier.id
  editMinQty.value = tier.minQty
  editPercent.value = String(tier.discountPercent)
  saveError.value = ''
  deleteError.value = null
}

function cancelEdit() {
  editingId.value = null
  saveError.value = ''
}

async function submitEdit(tier: VolumeTier) {
  if (saving.value) return
  const minQty = editMinQty.value
  const percent = parseNumber(editPercent.value)
  if (minQty == null || percent == null) return
  saving.value = true
  saveError.value = ''
  try {
    const updated = await repository.update(tier.id, tier.version, {
      minQty,
      discountPercent: percent,
    })
    tiers.value = tiers.value
      .map((item) => (item.id === updated.id ? updated : item))
      .sort((a, b) => a.minQty - b.minQty)
    cancelEdit()
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось сохранить ступень')
    if (problem.code === 'STALE_RESOURCE_VERSION') {
      saveError.value = 'Ступень уже изменена другим менеджером — список перечитан, проверьте значения и повторите.'
      await load()
    } else {
      saveError.value =
        problem.code === 'VOLUME_TIER_DUPLICATE_THRESHOLD'
          ? `Порог от ${minQty} шт уже занят`
          : problemMessage(problem, 'Не удалось сохранить ступень')
    }
  } finally {
    saving.value = false
  }
}

function confirmRemove(tier: VolumeTier) {
  deleteError.value = null
  saveError.value = ''
  confirmingId.value = confirmingId.value === tier.id ? null : tier.id
}

async function doRemove(tier: VolumeTier) {
  if (deletingId.value) return
  deletingId.value = tier.id
  deleteError.value = null
  try {
    await repository.remove(tier.id, tier.version)
    tiers.value = tiers.value.filter((item) => item.id !== tier.id)
    confirmingId.value = null
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось удалить ступень')
    const stale = problem.code === 'STALE_RESOURCE_VERSION'
    deleteError.value = {
      id: tier.id,
      msg: stale
        ? 'Ступень уже изменена другим менеджером — список перечитан, повторите удаление.'
        : problemMessage(problem, 'Не удалось удалить ступень'),
    }
    // Ступень могли переписать или удалить: показываем актуальное состояние.
    if (stale) {
      confirmingId.value = null
      await load()
    }
  } finally {
    deletingId.value = null
  }
}

watch(() => props.brandId, load)
onMounted(load)

defineExpose({ reload: load })
</script>

<template>
  <div data-testid="volume-tiers-panel">
    <p class="text-sm text-ink-muted">
      Скидка за объём действует на количество строки заказа: от 10 шт минус 2%, от 50 шт —
      минус 5%. Ступени не складываются, применяется одна — с наибольшим порогом, который
      количество уже достигло. Если у клиента есть своя скидка на бренд, действует большая из
      двух.
    </p>

    <div v-if="loading" class="mt-4 space-y-2">
      <div class="skeleton h-9 w-full" />
      <div class="skeleton h-9 w-full" />
    </div>

    <div v-else-if="loadError" class="mt-4 flex items-center gap-3">
      <div class="badge-danger">{{ loadError }}</div>
      <button type="button" class="btn-ghost min-h-11 text-xs" @click="load">Повторить</button>
    </div>

    <template v-else>
      <ul v-if="tiers.length" class="mt-4 divide-y divide-border border border-border">
        <li v-for="tier in tiers" :key="tier.id" class="p-3">
          <div v-if="editingId !== tier.id" class="flex items-center gap-3">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold">
                от {{ tier.minQty }} шт <span class="text-ink-muted">—</span>
                <!-- Пробел после тире держим отдельным текстовым узлом: без него он
                     схлопывается вместе с переносом строки в «—минус». -->
                <span class="text-success-text">&nbsp;минус {{ tier.discountPercent }}%</span>
              </p>
              <p class="text-xs text-ink-faint">версия {{ tier.version }}</p>
            </div>
            <button type="button" class="btn-ghost min-h-11 px-2 text-xs" @click="startEdit(tier)">
              <Icon name="heroicons:pencil" class="w-3.5 h-3.5" /> Изменить
            </button>
            <button type="button" class="btn-ghost min-h-11 px-2 text-xs text-danger" @click="confirmRemove(tier)">
              <Icon name="heroicons:trash" class="w-3.5 h-3.5" /> Удалить
            </button>
          </div>

          <!-- Правка ступени: оба поля опциональны, If-Match по версии ступени -->
          <div v-else class="flex flex-wrap items-end gap-3">
            <div>
              <label class="label" :for="`tier-min-${tier.id}`">От скольких шт</label>
              <input
                :id="`tier-min-${tier.id}`"
                v-model.number="editMinQty"
                type="number"
                class="input numeric"
                min="1"
                step="1"
              >
            </div>
            <div>
              <label class="label" :for="`tier-pct-${tier.id}`">Скидка, %</label>
              <input
                :id="`tier-pct-${tier.id}`"
                v-model="editPercent"
                type="text"
                inputmode="decimal"
                class="input numeric"
              >
            </div>
            <button
              type="button"
              class="btn-primary min-h-11"
              :disabled="saving"
              :data-testid="`volume-tier-save-${tier.id}`"
              @click="submitEdit(tier)"
            >
              <span v-if="saving" class="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-sm animate-spin" />
              Сохранить
            </button>
            <button type="button" class="btn-ghost min-h-11" :disabled="saving" @click="cancelEdit">Отмена</button>
          </div>
          <p v-if="saveError && editingId === tier.id" class="text-xs text-danger mt-2">{{ saveError }}</p>

          <!-- Подтверждение удаления -->
          <div v-if="confirmingId === tier.id" class="mt-3 flex flex-wrap items-center gap-2 p-3 border border-border bg-danger-soft">
            <span class="text-xs text-danger flex-1">Удалить ступень «от {{ tier.minQty }} шт — {{ tier.discountPercent }}%»?</span>
            <button
              type="button"
              class="btn-outline min-h-11 px-3 text-xs text-danger"
              :disabled="deletingId === tier.id"
              @click="doRemove(tier)"
            >
              <span v-if="deletingId === tier.id" class="w-3 h-3 border-2 border-white/40 border-t-white rounded-sm animate-spin" />
              {{ deletingId === tier.id ? 'Удаление…' : 'Удалить' }}
            </button>
            <button type="button" class="btn-ghost min-h-11 px-3 text-xs" @click="confirmingId = null">Отмена</button>
          </div>
          <p v-if="deleteError?.id === tier.id" class="text-xs text-danger mt-2">{{ deleteError.msg }}</p>
        </li>
      </ul>

      <p v-else class="mt-4 border border-border bg-surface p-3 text-sm text-ink-faint">
        Ступеней пока нет — цена считается по обычной скидке на бренд.
      </p>

      <p v-if="nextThresholdHint" class="text-xs text-ink-faint mt-2">{{ nextThresholdHint }}</p>

      <!-- Добавление ступени -->
      <div class="mt-5 border border-border bg-surface p-3">
        <p class="text-sm font-semibold mb-3">Добавить ступень</p>
        <div class="flex flex-wrap items-end gap-3">
          <div>
            <label class="label" for="volume-tier-new-min">От скольких шт <span class="text-danger">*</span></label>
            <input
              id="volume-tier-new-min"
              v-model.number="newMinQty"
              type="number"
              class="input numeric w-32"
              min="1"
              step="1"
              placeholder="10"
            >
          </div>
          <div>
            <label class="label" for="volume-tier-new-pct">Скидка, % <span class="text-danger">*</span></label>
            <input
              id="volume-tier-new-pct"
              v-model="newPercent"
              type="text"
              inputmode="decimal"
              class="input numeric w-32"
              placeholder="2"
            >
          </div>
          <button
            type="button"
            class="btn-primary min-h-11"
            :disabled="!canCreate || creating"
            data-testid="volume-tier-create"
            @click="submitCreate"
          >
            <span v-if="creating" class="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-sm animate-spin" />
            Добавить
          </button>
        </div>
        <p class="text-xs text-ink-faint mt-2">
          Порог от 1 шт и больше, скидка строго от 0 до 100. Один порог на бренд — повтор не даст
          добавить.
        </p>
        <div v-if="createError" class="badge-danger w-full justify-center py-2 mt-3">{{ createError }}</div>
      </div>
    </template>
  </div>
</template>
