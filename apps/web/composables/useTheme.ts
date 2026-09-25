export type Theme = 'light' | 'dark'

export function useTheme() {
  const colorMode = useColorMode()
  const mode = computed<Theme>({
    get: () => (colorMode.value === 'dark' ? 'dark' : 'light'),
    set: (value: Theme) => {
      colorMode.preference = value
    },
  })

  function apply(theme: Theme): void {
    colorMode.preference = theme
  }

  function toggle(): void {
    apply(mode.value === 'dark' ? 'light' : 'dark')
  }

  return { mode, apply, toggle }
}
