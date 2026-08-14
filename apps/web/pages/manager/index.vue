<script setup lang="ts">
// Дашборд менеджера (фича G). Каркас.
// Реальные агрегаты — на Этапе 8 (GET /api/v1/manager/dashboard).
definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER'] })
useHead({ title: 'Дашборд' })

const kpis = [
  { label: 'Заявок сегодня', value: '—', icon: 'heroicons:clipboard-document', tone: 'primary' },
  { label: 'Выручка за месяц', value: '—', icon: 'heroicons:banknotes', tone: 'success' },
  { label: 'Новых клиентов', value: '—', icon: 'heroicons:user-plus', tone: 'secondary' },
  { label: 'Активных импортов', value: '0', icon: 'heroicons:arrow-up-tray', tone: 'warning' },
]
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold mb-6">Дашборд</h1>

    <div class="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
      <div v-for="kpi in kpis" :key="kpi.label" class="card p-5">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm text-ink-muted">{{ kpi.label }}</span>
          <span :class="`badge-${kpi.tone}`"><Icon :name="kpi.icon" class="w-3.5 h-3.5" /></span>
        </div>
        <p class="text-2xl font-bold">{{ kpi.value }}</p>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <div class="card p-6">
        <h3 class="font-semibold mb-4">Заявки по дням</h3>
        <div class="h-48 flex items-center justify-center text-ink-faint text-sm">
          График появится на Этапе 8
        </div>
      </div>
      <div class="card p-6">
        <h3 class="font-semibold mb-4">Последние заявки</h3>
        <div class="h-48 flex items-center justify-center text-ink-faint text-sm">
          Лента появится на Этапе 8
        </div>
      </div>
    </div>
  </div>
</template>
