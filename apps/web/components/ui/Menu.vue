<script setup lang="ts">
export interface MenuItem {
  id: string
  label: string
  disabled?: boolean
  destructive?: boolean
}

const props = withDefaults(
  defineProps<{
    label: string
    items: MenuItem[]
    align?: 'start' | 'end'
  }>(),
  { align: 'start' },
)
const emit = defineEmits<{ select: [item: MenuItem] }>()
const uid = useId()
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)
const selectable = computed(() => props.items.filter((item) => !item.disabled))

function itemId(id: string): string {
  return `${uid}-${id}`
}
function openMenu(startAt: 'first' | 'last' = 'first'): void {
  open.value = true
  activeIndex.value = startAt === 'last' ? selectable.value.length - 1 : 0
  nextTick(focusActive)
}
function close(restoreFocus = false): void {
  open.value = false
  activeIndex.value = -1
  if (restoreFocus) trigger.value?.focus()
}
function toggle(): void {
  if (open.value) close()
  else openMenu()
}
function focusActive(): void {
  const item = selectable.value[activeIndex.value]
  if (item) document.getElementById(itemId(item.id))?.focus()
}
function choose(item: MenuItem): void {
  if (item.disabled) return
  emit('select', item)
  close(true)
}
function onKeydown(event: KeyboardEvent): void {
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault()
      openMenu(event.key === 'ArrowUp' ? 'last' : 'first')
    }
    return
  }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Escape'].includes(event.key)) {
    event.preventDefault()
    if (event.key === 'Escape') close(true)
    else if (event.key === 'Home') activeIndex.value = 0
    else if (event.key === 'End') activeIndex.value = selectable.value.length - 1
    else {
      const offset = event.key === 'ArrowDown' ? 1 : -1
      activeIndex.value =
        (activeIndex.value + offset + selectable.value.length) % selectable.value.length
    }
    nextTick(focusActive)
  }
}
function onDocumentPointerDown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))
onUnmounted(() => document.removeEventListener('pointerdown', onDocumentPointerDown))
</script>

<template>
  <div ref="root" class="relative inline-block" @keydown="onKeydown">
    <button
      ref="trigger"
      type="button"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-controls="`${uid}-menu`"
      class="inline-flex min-h-9 items-center gap-2 border border-border-strong bg-surface px-3 py-1.5 text-sm font-semibold text-ink hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
      :disabled="items.length === 0"
      @click="toggle"
    >
      <slot name="trigger" :open="open">{{ label }}</slot>
      <Icon name="heroicons:chevron-down" class="size-4 text-ink-muted" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      :id="`${uid}-menu`"
      role="menu"
      :aria-orientation="'vertical'"
      class="absolute z-50 mt-1 min-w-56 border border-border-strong bg-surface p-1 shadow-overlay"
      :class="align === 'end' ? 'right-0' : 'left-0'"
    >
      <button
        v-for="item in items"
        :id="itemId(item.id)"
        :key="item.id"
        type="button"
        role="menuitem"
        tabindex="-1"
        :disabled="item.disabled"
        class="flex min-h-9 w-full items-center gap-2 px-3 py-1.5 text-left text-sm font-medium hover:bg-surface-2 focus:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
        :class="item.destructive ? 'text-danger-text' : 'text-ink'"
        @click="choose(item)"
        @mouseenter="activeIndex = selectable.findIndex((option) => option.id === item.id)"
      >
        <slot :name="`item-${item.id}`" :item="item">{{ item.label }}</slot>
      </button>
      <slot />
    </div>
  </div>
</template>
