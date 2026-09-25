<script setup lang="ts">
useHead({
  meta: [
    { name: 'theme-color', content: '#f5f2eb' },
    { name: 'color-scheme', content: 'light dark' },
  ],
})
</script>

<template>
  <div class="flex min-h-dvh flex-col bg-background text-ink">
    <a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-border focus:bg-surface focus:px-4 focus:py-3 focus:text-ink">Перейти к содержимому</a>
    <PublicHeader />
    <main id="main-content" class="min-w-0 flex-1">
      <slot />
    </main>
    <PublicFooter />
  </div>
</template>
