<script setup lang="ts">
export interface LandingTestimonial {
  quote: string
  name: string
  role?: string
  company?: string
}

const props = withDefaults(
  defineProps<{
    testimonials?: LandingTestimonial[]
    title?: string
  }>(),
  {
    testimonials: () => [],
    title: 'Отзывы клиентов',
  },
)
</script>

<template>
  <section v-if="props.testimonials.length" class="border-y border-border bg-surface py-14 lg:py-20" :aria-labelledby="'landing-testimonials-title'">
    <div class="container-app">
      <h2 id="landing-testimonials-title" class="text-3xl font-bold text-ink">{{ title }}</h2>
      <div class="mt-8 divide-y divide-border border-y border-border">
        <figure v-for="testimonial in props.testimonials" :key="`${testimonial.name}-${testimonial.quote}`" class="grid gap-4 py-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-10">
          <blockquote class="text-lg font-medium leading-8 text-ink">«{{ testimonial.quote }}»</blockquote>
          <figcaption class="text-sm text-ink-muted lg:text-right">
            <span class="block font-semibold text-ink">{{ testimonial.name }}</span>
            <span v-if="testimonial.role || testimonial.company" class="mt-1 block">
              {{ [testimonial.role, testimonial.company].filter(Boolean).join(', ') }}
            </span>
          </figcaption>
        </figure>
      </div>
    </div>
  </section>
</template>
