<script setup lang="ts">
// Вертикальная временная шкала статусов заявки (новые — внизу, последний статус подсвечен).
export interface TimelineItem {
  status: string
  created_at: string
  comment?: string | null
}

const props = defineProps<{ items: TimelineItem[] }>()

const STATUS_LABELS: Record<string, string> = {
  NEW: 'Новая',
  IN_PROGRESS: 'В работе',
  SHIPPED: 'Отгружена',
  COMPLETED: 'Завершена',
  CANCELLED: 'Отменена',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status
}

const ordered = computed(() => [...props.items].reverse())
</script>

<template>
  <ol class="relative">
    <li
      v-for="(item, i) in ordered"
      :key="i"
      class="relative pl-6 pb-5 last:pb-0 border-l-2 border-border"
    >
      <span
        class="absolute -left-[7px] top-1 w-3 h-3 rounded-full ring-2 ring-surface"
        :class="i === ordered.length - 1 ? 'bg-primary' : 'bg-border'"
      />
      <p class="text-sm font-semibold leading-snug">{{ statusLabel(item.status) }}</p>
      <p class="text-xs text-ink-faint mt-0.5">{{ formatDateTime(item.created_at) }}</p>
      <div
        v-if="item.comment"
        class="mt-2 text-sm text-ink-muted bg-canvas border border-border/60 rounded-card px-3 py-2"
      >
        {{ item.comment }}
      </div>
    </li>
  </ol>
</template>
