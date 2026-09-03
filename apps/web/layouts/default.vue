<script setup lang="ts">
// Layout для публичных страниц (без sidebar).
// Авторизованные видят упрощённую шапку (AppHeader), гости — только «Войти».
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <main class="flex-1">
      <slot />
    </main>
    <AppFooter />
  </div>
</template>
