// Переключатель тёмной темы (карточка «Оформление» в /profile).
// Выбранная тема хранится в localStorage этого браузера; класс `dark`
// вешается на <html> (переключатель в /profile, карточка «Оформление»).

export type Theme = 'light' | 'dark'

const THEME_STORAGE_KEY = 'theme'

// Состояние — на уровне модуля: одна тема на всё приложение.
const mode = ref<Theme>('light')

export function useTheme() {
  function apply(theme: Theme): void {
    mode.value = theme
    if (!import.meta.client) return
    localStorage.setItem(THEME_STORAGE_KEY, theme)
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }

  function toggle(): void {
    apply(mode.value === 'dark' ? 'light' : 'dark')
  }

  /** Восстановить сохранённую тему при старте (клиент). */
  function init(): void {
    if (!import.meta.client) return
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    apply(saved === 'dark' ? 'dark' : 'light')
  }

  return { mode, apply, toggle, init }
}
