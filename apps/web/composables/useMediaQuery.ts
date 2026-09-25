import type { MaybeRefOrGetter, Ref } from 'vue'

function resolveSource(value: MaybeRefOrGetter<string>) {
  return toValue(value)
}

export function useMediaQuery(query: MaybeRefOrGetter<string>): Readonly<Ref<boolean>> {
  const matches = ref(false)
  let mediaQuery: MediaQueryList | null = null

  function update(event?: MediaQueryListEvent): void {
    matches.value = event?.matches ?? mediaQuery?.matches ?? false
  }

  function subscribe(): void {
    if (!import.meta.client) return
    mediaQuery?.removeEventListener('change', update)
    mediaQuery = window.matchMedia(resolveSource(query))
    update()
    mediaQuery.addEventListener('change', update)
  }

  watch(() => resolveSource(query), subscribe, { immediate: true })
  onScopeDispose(() => mediaQuery?.removeEventListener('change', update))

  return readonly(matches)
}
