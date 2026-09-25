<script setup lang="ts">
import type { OrderStatus } from '~/domain/api/v2/order.schema'

const props = defineProps<{
  status: OrderStatus
}>()

const normalStatuses = ['NEW', 'IN_PROGRESS', 'SHIPPED', 'COMPLETED'] as const
const labels: Record<OrderStatus, string> = {
  NEW: 'Заявка принята',
  IN_PROGRESS: 'Сборка и расчёт',
  SHIPPED: 'Передано в доставку',
  COMPLETED: 'Заявка завершена',
  CANCELLED: 'Заявка отменена',
}

const currentIndex = computed(() =>
  props.status === 'CANCELLED'
    ? -1
    : normalStatuses.indexOf(props.status as (typeof normalStatuses)[number]),
)

const steps = computed(() => {
  if (props.status === 'CANCELLED') {
    return [
      { key: 'CANCELLED' as const, label: labels.CANCELLED, state: 'active' as const },
    ]
  }

  return normalStatuses.map((key, index) => ({
    key,
    label: labels[key],
    state:
      index < currentIndex.value
        ? ('done' as const)
        : index === currentIndex.value
          ? ('active' as const)
          : ('pending' as const),
  }))
})
</script>

<template>
  <ol
    class="border-l border-border-strong"
    data-testid="order-detail-timeline"
    aria-label="Статус заявки"
  >
    <li
      v-for="(step, index) in steps"
      :key="step.key"
      class="relative pb-5 pl-6 last:pb-0"
    >
      <span
        class="absolute -left-[7px] top-0.5 flex size-3.5 items-center justify-center border"
        :class="
          step.state === 'active'
            ? 'border-action bg-action text-action-on'
            : step.state === 'done'
              ? 'border-success bg-success text-action-on'
              : 'border-border-strong bg-surface text-ink-muted'
        "
        aria-hidden="true"
      >
        <Icon v-if="step.state === 'done'" name="heroicons:check" class="size-2.5" />
        <span v-else class="size-1 bg-current" />
      </span>
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p
          class="text-sm font-semibold"
          :class="step.state === 'pending' ? 'text-ink-muted' : 'text-ink'"
        >
          {{ step.label }}
        </p>
        <span class="numeric text-xs text-ink-muted">
          {{ String(index + 1).padStart(2, '0') }}
        </span>
      </div>
      <p v-if="step.state === 'active'" class="mt-0.5 text-xs text-ink-muted" aria-current="step">
        Текущий этап
      </p>
    </li>
  </ol>
</template>
