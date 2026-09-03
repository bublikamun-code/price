// Переключатель тёмной/светлой темы (карточка «Оформление» в /profile).
// Реальный механизм — модуль @nuxtjs/color-mode: он вешает класс `dark`
// на <html> и хранит выбор в localStorage (`nuxt-color-mode`).
// Дефолт — тёмная (nuxt.config → colorMode.preference).
export type Theme = 'light' | 'dark'

export function useTheme() {
  const colorMode = useColorMode()

  const mode = computed<Theme>({
    get: () => (colorMode.value === 'dark' ? 'dark' : 'light'),
    set: (v: Theme) => { colorMode.preference = v },
  })

  /** Применить тему (модуль сам обновит <html> и localStorage). */
  function apply(theme: Theme): void {
    colorMode.preference = theme
  }

  function toggle(): void {
    apply(mode.value === 'dark' ? 'light' : 'dark')
  }

  /** Совместимость: модуль сам инициализируется до отрисовки, делать нечего. */
  function init(): void {}

  return { mode, apply, toggle, init }
}
