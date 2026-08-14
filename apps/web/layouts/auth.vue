<script setup lang="ts">
// Минимальный layout для страниц аутентификации (без навигации).
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-canvas px-4">
    <div class="w-full max-w-md">
      <NuxtLink to="/" class="flex items-center justify-center mb-8">
        <span class="font-display text-2xl font-bold text-primary">Price<span class="text-ink">Portal</span></span>
      </NuxtLink>
      <slot />
    </div>
  </div>
</template>
