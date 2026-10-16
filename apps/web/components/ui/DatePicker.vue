<script setup lang="ts">
interface DayCell {
  y: number
  m: number // 1-12
  d: number
}

const props = withDefaults(
  defineProps<{
    modelValue?: string // ISO yyyy-mm-dd или ''
    id?: string
    disabled?: boolean
    placeholder?: string
    align?: 'start' | 'end'
  }>(),
  {
    modelValue: '',
    id: undefined,
    disabled: false,
    placeholder: 'дд.мм.гггг',
    align: 'start',
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const MONTHS = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const open = ref(false)
const view = ref<{ y: number; m: number }>({ y: 0, m: 1 })

function parseIso(value: string): DayCell | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) } : null
}
function isoOf(cell: DayCell): string {
  return `${String(cell.y).padStart(4, '0')}-${String(cell.m).padStart(2, '0')}-${String(cell.d).padStart(2, '0')}`
}
function pad2(n: number): string {
  return String(n).padStart(2, '0')
}
function today(): DayCell {
  const now = new Date()
  return { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() }
}
function sameDay(a: DayCell, b: DayCell): boolean {
  return a.y === b.y && a.m === b.m && a.d === b.d
}

const selected = computed(() => parseIso(props.modelValue))
const display = computed(() => {
  const s = selected.value
  return s ? `${pad2(s.d)}.${pad2(s.m)}.${s.y}` : ''
})
const clearable = computed(() => Boolean(display.value) && !props.disabled)
const viewTitle = computed(() => `${MONTHS[view.value.m - 1]} ${view.value.y}`)

const cells = computed<DayCell[]>(() => {
  const { y, m } = view.value
  const first = new Date(y, m - 1, 1)
  const offset = (first.getDay() + 6) % 7 // Пн = 0
  const start = new Date(y, m - 1, 1 - offset)
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() }
  })
})

const activeCell = computed<DayCell>(() => {
  const inView = (c: DayCell) => c.y === view.value.y && c.m === view.value.m
  const t = today()
  if (selected.value && inView(selected.value)) return selected.value
  if (inView(t)) return t
  return cells.value.find(inView) ?? cells.value[0]
})

function cellClass(cell: DayCell): string[] {
  const isSelected = selected.value ? sameDay(cell, selected.value) : false
  const isToday = sameDay(cell, today())
  return [
    // bg-service не инвертируется в тёмной теме — плашка и текст остаются контрастными.
    isSelected ? 'bg-service font-semibold text-ink-on-service' : 'text-ink hover:bg-surface-2',
    !isSelected && isToday ? 'border border-ink font-semibold' : 'border border-transparent',
    !isSelected && cell.m !== view.value.m ? 'text-ink-muted' : '',
  ]
}

function focusCell(cell: DayCell): void {
  popup.value?.querySelector<HTMLButtonElement>(`[data-iso="${isoOf(cell)}"]`)?.focus()
}

function openPopup(): void {
  if (props.disabled || open.value) return
  const base = selected.value ?? today()
  view.value = { y: base.y, m: base.m }
  open.value = true
  nextTick(() => focusCell(activeCell.value))
}
function close(restoreFocus = false): void {
  if (!open.value) return
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
function toggle(): void {
  if (open.value) close(true)
  else openPopup()
}

function choose(cell: DayCell): void {
  emit('update:modelValue', isoOf(cell))
  close(true)
}
function chooseToday(): void {
  const t = today()
  view.value = { y: t.y, m: t.m }
  emit('update:modelValue', isoOf(t))
  nextTick(() => focusCell(activeCell.value))
}
function clearValue(): void {
  emit('update:modelValue', '')
  close(true)
}
function shiftMonth(delta: number): void {
  const total = view.value.y * 12 + (view.value.m - 1) + delta
  view.value = { y: Math.floor(total / 12), m: (total % 12) + 1 }
  nextTick(() => focusCell(activeCell.value))
}

function onGridKeydown(event: KeyboardEvent): void {
  const current = activeCell.value
  const moveBy = (days: number): void => {
    event.preventDefault()
    const d = new Date(current.y, current.m - 1, current.d + days)
    const target: DayCell = { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() }
    if (target.y !== view.value.y || target.m !== view.value.m) {
      view.value = { y: target.y, m: target.m }
    }
    nextTick(() => focusCell(target))
  }
  switch (event.key) {
    case 'ArrowLeft':
      moveBy(-1)
      break
    case 'ArrowRight':
      moveBy(1)
      break
    case 'ArrowUp':
      moveBy(-7)
      break
    case 'ArrowDown':
      moveBy(7)
      break
    case 'Home':
      event.preventDefault()
      focusCell({ y: view.value.y, m: view.value.m, d: 1 })
      break
    case 'End':
      event.preventDefault()
      focusCell({
        y: view.value.y,
        m: view.value.m,
        d: new Date(view.value.y, view.value.m, 0).getDate(),
      })
      break
    case 'PageUp':
      event.preventDefault()
      shiftMonth(-1)
      break
    case 'PageDown':
      event.preventDefault()
      shiftMonth(1)
      break
    case 'Escape':
      event.preventDefault()
      close(true)
      break
  }
}
function onDocumentPointerDown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))
onUnmounted(() => document.removeEventListener('pointerdown', onDocumentPointerDown))
</script>

<template>
  <div ref="root" class="relative min-w-0">
    <button
      :id="id"
      ref="trigger"
      type="button"
      :disabled="disabled"
      aria-haspopup="dialog"
      :aria-expanded="open"
      class="flex min-h-11 w-full items-center justify-between gap-2 border bg-surface px-3 py-1.5 text-left text-sm transition-colors duration-100 disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-muted lg:min-h-9"
      :class="open ? 'border-focus ring-1 ring-focus' : 'border-border-strong'"
      @click="toggle"
    >
      <span class="truncate" :class="display ? 'text-ink' : 'text-ink-muted'">
        {{ display || placeholder }}
      </span>
      <Icon
        v-if="!clearable"
        name="heroicons:calendar-days"
        class="size-4 shrink-0 text-ink-muted"
        aria-hidden="true"
      />
    </button>
    <button
      v-if="clearable"
      type="button"
      aria-label="Очистить дату"
      class="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-ink-muted hover:text-ink"
      @click="clearValue"
    >
      <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      ref="popup"
      role="dialog"
      aria-label="Выбор даты"
      class="absolute z-50 mt-1 w-72 border border-border-strong bg-surface p-3 shadow-overlay"
      :class="align === 'end' ? 'right-0' : 'left-0'"
      @keydown="onGridKeydown"
    >
      <div class="flex items-center justify-between">
        <button
          type="button"
          aria-label="Предыдущий месяц"
          class="flex size-8 items-center justify-center text-ink-muted transition-colors duration-100 hover:bg-surface-2 hover:text-ink"
          @click="shiftMonth(-1)"
        >
          <Icon name="heroicons:chevron-left" class="size-4" aria-hidden="true" />
        </button>
        <p class="text-sm font-semibold text-ink" aria-live="polite">{{ viewTitle }}</p>
        <button
          type="button"
          aria-label="Следующий месяц"
          class="flex size-8 items-center justify-center text-ink-muted transition-colors duration-100 hover:bg-surface-2 hover:text-ink"
          @click="shiftMonth(1)"
        >
          <Icon name="heroicons:chevron-right" class="size-4" aria-hidden="true" />
        </button>
      </div>
      <div class="mt-2 grid grid-cols-7" aria-hidden="true">
        <span
          v-for="weekday in WEEKDAYS"
          :key="weekday"
          class="flex h-7 items-center justify-center text-[11px] font-semibold uppercase text-ink-muted"
        >
          {{ weekday }}
        </span>
      </div>
      <div class="grid grid-cols-7 gap-0.5">
        <button
          v-for="cell in cells"
          :key="isoOf(cell)"
          type="button"
          :data-iso="isoOf(cell)"
          :tabindex="sameDay(cell, activeCell) ? 0 : -1"
          :aria-current="sameDay(cell, today()) ? 'date' : undefined"
          class="flex size-9 items-center justify-center text-sm transition-colors duration-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-focus"
          :class="cellClass(cell)"
          @click="choose(cell)"
        >
          {{ cell.d }}
        </button>
      </div>
      <div class="mt-2 flex items-center justify-between border-t border-border pt-2">
        <button
          type="button"
          class="px-1 py-1 text-xs font-medium text-ink-muted transition-colors duration-100 hover:text-ink"
          @click="clearValue"
        >
          Очистить
        </button>
        <button
          type="button"
          class="px-1 py-1 text-xs font-semibold text-ink transition-colors duration-100 hover:bg-surface-2"
          @click="chooseToday"
        >
          Сегодня
        </button>
      </div>
    </div>
  </div>
</template>
