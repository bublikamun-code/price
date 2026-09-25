<script setup lang="ts">
// Компактный клиентский дом (route /dashboard): заявки, избранное, файлы,
// баннеры и новости. Раньше этот экран жил на / под веткой «авторизованный
// клиент»; теперь / — всегда публичный лендинг, а сюда пускает только
// авторизованный клиент (auth + role CLIENT). Содержимое вынесено в
// components/client/ClientHomeDashboard.vue; /dashboard — тонкая обёртка
// с client-layout (сайдбар, шапка и noindex-robots идут из layout).
definePageMeta({ layout: 'client', middleware: ['auth', 'role'], roles: ['CLIENT'] })
useHead({ title: 'Главная' })
</script>

<template>
  <ClientHomeDashboard />
</template>
