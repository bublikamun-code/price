// useCountUp: анимированный счётчик — число «набегает» от 0 до target
// при попадании элемента во viewport (IntersectionObserver).
// Учитывает prefers-reduced-motion.
export function useCountUp(target: number, duration = 1500) {
  const display = ref(0)
  const el = shallowRef<HTMLElement | null>(null)
  let started = false

  function animate() {
    if (started) return
    started = true
    const start = performance.now()
    const step = (now: number) => {
      const progress = Math.min((now - start) / duration, 1)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3)
      display.value = Math.round(eased * target)
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  onMounted(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || !el.value) {
      display.value = target
      return
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          animate()
          io.disconnect()
        }
      },
      { threshold: 0.3 },
    )
    io.observe(el.value)
  })

  return { display, el }
}
