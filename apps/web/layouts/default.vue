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
    <footer class="border-t border-border bg-surface">
      <div class="container-app py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-ink-muted">
        <p>© {{ new Date().getFullYear() }} Клиентский портал</p>
        <nav class="flex items-center gap-5">
          <NuxtLink to="/privacy" class="hover:text-primary">Политика конфиденциальности</NuxtLink>
          <a href="#" class="hover:text-primary">Контакты</a>
        </nav>
      </div>
    </footer>
  </div>
</template>
