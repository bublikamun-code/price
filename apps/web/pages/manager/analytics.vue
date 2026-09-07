<script setup lang="ts">
definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Аналитика' })
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold mb-6">Аналитика</h1>
    <div class="card p-8 text-center">
      <Icon name="heroicons:chart-bar" class="w-16 h-16 mx-auto mb-4 text-ink-faint" />
      <h2 class="text-xl font-semibold mb-2">Раздел в разработке</h2>
      <p class="text-ink-muted mb-6">
        Аналитический дашборд с графиками продаж, динамикой цен и отчётами скоро будет доступен.
      </p>
      <NuxtLink to="/manager" class="btn-primary">← Назад на дашборд</NuxtLink>
    </div>
  </div>
</template>
