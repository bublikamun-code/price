<script setup lang="ts">
// Layout для страниц аутентификации: форма по центру + footer внизу.
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <div class="flex-1 flex items-center justify-center px-4 py-8">
      <div class="w-full max-w-md">
        <NuxtLink to="/" class="flex items-center justify-center mb-8">
          <span class="font-display text-2xl font-bold text-primary">Price<span class="text-ink">Portal</span></span>
        </NuxtLink>
        <slot />
      </div>
    </div>
    <AppFooter />
  </div>
</template>
