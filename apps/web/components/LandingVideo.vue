<script setup lang="ts">
withDefaults(
  defineProps<{
    src?: string
    title?: string
    poster?: string
  }>(),
  {
    src: '',
    title: 'Обзор кабинета',
    poster: undefined,
  },
)
</script>

<template>
  <section v-if="src" class="border-y border-border bg-surface py-12 lg:py-16" aria-labelledby="landing-video-title">
    <div class="container-app grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-10">
      <div>
        <p class="text-sm font-semibold text-ink-muted">Материал</p>
        <h2 id="landing-video-title" class="mt-2 text-2xl font-bold text-ink">{{ title }}</h2>
      </div>
      <video controls preload="metadata" :poster="poster" class="aspect-video w-full bg-service object-contain">
        <source :src="src">
        Ваш браузер не поддерживает воспроизведение видео.
      </video>
    </div>
  </section>
</template>
