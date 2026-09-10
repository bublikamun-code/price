// Директива v-reveal: плавное появление блока при попадании во viewport.
// SSR — пустые props (директива чисто клиентская); на клиенте mounted
// гасит элемент и раскрывает его при первом пересечении. Уважает
// prefers-reduced-motion (глобальный guard в main.css тоже на страже).
export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.vueApp.directive('reveal', {
    getSSRProps: () => ({}),
    mounted(el: HTMLElement) {
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      if (reduced) return
      el.style.opacity = '0'
      el.style.transform = 'translateY(18px)'
      el.style.transition = 'opacity 0.6s ease, transform 0.6s cubic-bezier(0.4, 0, 0.2, 1)'
      const io = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              el.style.opacity = '1'
              el.style.transform = 'none'
              io.disconnect()
            }
          }
        },
        { threshold: 0.12 },
      )
      io.observe(el)
    },
  })
})
