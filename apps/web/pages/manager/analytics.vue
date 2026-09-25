<script setup lang="ts">
definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Аналитика недоступна' })
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Аналитика"
      description="Сводные отчёты появятся после подтверждения API-контракта."
    />
    <UiPanel>
      <p class="text-sm font-semibold text-ink">Раздел недоступен</p>
      <p class="mt-1 max-w-2xl text-sm leading-5 text-ink-muted">В API v1 нет подтверждённого контракта аналитических отчётов. Этот маршрут не обещает данные и не запускает фиктивные запросы.</p>
      <NuxtLink to="/manager" class="btn-primary mt-4 inline-flex min-h-11 items-center">Вернуться к обзору</NuxtLink>
    </UiPanel>
  </div>
</template>
