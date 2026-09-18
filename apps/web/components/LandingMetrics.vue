<!-- Metrics: social proof for B2B trust — animated counters + brand trust bar -->
<template>
  <section ref="sectionRef" class="bg-surface border-y border-border py-10 lg:py-14">
    <div class="container-app">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-8 md:gap-4 text-center">
        <div v-for="(m, i) in metrics" :key="m.label">
          <div class="text-3xl lg:text-4xl font-bold text-accent mb-1">
            {{ displayValues[i] }}{{ m.target === 0 ? '' : m.suffix }}
          </div>
          <div class="text-sm text-ink-muted">{{ m.label }}</div>
        </div>
      </div>

      <!-- Trust bar: brand marquee -->
      <div class="mt-10 pt-8 border-t border-border overflow-hidden">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-ink-faint text-center mb-6">
          Нам доверяют
        </p>
        <div class="marquee-mask">
          <div class="flex gap-16 animate-marquee">
            <div
              v-for="(b, i) in [...brands, ...brands]"
              :key="i"
              class="flex items-center gap-3 shrink-0"
            >
              <div class="w-10 h-10 rounded-pill bg-accent-soft flex items-center justify-center text-accent font-bold text-sm">
                {{ b.charAt(0) }}
              </div>
              <span class="text-base font-semibold text-ink-muted whitespace-nowrap">{{ b }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
const props = defineProps<{
  /** Живые данные из витрины: количество товаров (products) и брендов (brands) */
  productsCount?: number
  brandsCount?: number
}>()

const metrics = computed(() => [
  { target: props.brandsCount || 150, suffix: '+', label: 'Брендов и партнёров' },
  { target: props.productsCount || 10000, suffix: '+', label: 'Позиций в каталоге' },
  { target: 0, suffix: '24 ч', label: 'Подтверждение заявки' },
  { target: 8, suffix: ' лет', label: 'На рынке электротехники' },
])

const brands = ['КЭАЗ', 'SmartWatt', 'Rostok', 'OptiBox Pro']

const sectionRef = ref<HTMLElement | null>(null)
const displayValues = ref(metrics.value.map((m) => (m.target === 0 ? m.suffix : '0')))
let animated = false

function fmtNum(n: number): string {
  return n >= 1000 ? n.toLocaleString('ru-RU') : String(n)
}

function finalValues() {
  return metrics.value.map((m) => (m.target === 0 ? m.suffix : fmtNum(m.target)))
}

function animateCounters() {
  if (animated) return
  animated = true
  const current = metrics.value
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced) {
    displayValues.value = finalValues()
    return
  }
  const duration = 1500
  const start = performance.now()
  const step = (now: number) => {
    const progress = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    displayValues.value = current.map((m) => {
      if (m.target === 0) return m.suffix
      return fmtNum(Math.round(eased * m.target))
    })
    if (progress < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

onMounted(() => {
  nextTick(() => {
    const el = sectionRef.value
    if (!el) {
      displayValues.value = finalValues()
      return
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          animateCounters()
          io.disconnect()
        }
      },
      { threshold: 0.3 },
    )
    io.observe(el)
  })
})
</script>

<style scoped>
.animate-marquee {
  animation: marquee 20s linear infinite;
}
@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.marquee-mask {
  mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
  -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
}
</style>
