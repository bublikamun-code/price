<template>
  <section class="container-app py-16 lg:py-20">
    <p class="text-xs font-semibold uppercase tracking-[0.2em] text-ink-faint mb-2">Как это работает</p>
    <h2 class="text-3xl font-bold mb-8">Портал за 60 секунд</h2>
    <div
      class="relative rounded-card overflow-hidden bg-surface-2 border border-border cursor-pointer group"
      :class="{ 'aspect-video': !playing }"
      @click="play"
    >
      <!-- Placeholder -->
      <div v-if="!playing" class="absolute inset-0 flex flex-col items-center justify-center">
        <div class="absolute inset-0 bg-gradient-to-br from-primary-soft to-accent-soft opacity-50" />
        <div class="relative z-10 flex flex-col items-center">
          <div
            class="w-20 h-20 rounded-pill bg-accent flex items-center justify-center shadow-lg
                   group-hover:scale-110 transition-transform duration-300"
          >
            <Icon name="heroicons:play" class="w-8 h-8 text-white ml-1" />
          </div>
          <p class="mt-4 text-sm text-ink-muted">Посмотреть обзор кабинета</p>
        </div>
      </div>

      <!-- Video iframe (loads on click) -->
      <iframe
        v-if="playing"
        :src="videoSrc"
        class="w-full aspect-video"
        frameborder="0"
        allow="autoplay; fullscreen"
        allowfullscreen
      />
    </div>
  </section>
</template>

<script setup lang="ts">
const playing = ref(false)
// Replace with actual video embed URL when available
const videoSrc = ref('')

function play() {
  if (!videoSrc.value) return // No video yet — placeholder only
  playing.value = true
}
</script>
