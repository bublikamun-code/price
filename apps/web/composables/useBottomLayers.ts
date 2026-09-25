/**
 * Shared owner of the mobile bottom lanes.
 *
 * The lowest lane is the client navigation, which only exists inside the client
 * layout; a sticky action bar can sit above it on cart/checkout. Neither height
 * is known to a global layer such as the toast viewport or the cookie banner, so
 * components publish their own measured height here instead of each layer
 * guessing an offset. A lane that is not mounted reports 0.
 */
const navLayerHeight = ref(0)
const stickyLayerHeight = ref(0)

export function useBottomLayers() {
  return { navLayerHeight, stickyLayerHeight }
}

function publishHeight(root: Ref<HTMLElement | null>, target: Ref<number>): void {
  let observer: ResizeObserver | null = null

  onMounted(() => {
    const publish = () => {
      target.value = root.value ? Math.round(root.value.offsetHeight) : 0
    }
    publish()
    observer = new ResizeObserver(publish)
    if (root.value) observer.observe(root.value)
  })

  onUnmounted(() => {
    observer?.disconnect()
    observer = null
    target.value = 0
  })
}

/** The client navigation owns the lowest bottom lane. */
export function useNavLayer(root: Ref<HTMLElement | null>): void {
  publishHeight(root, navLayerHeight)
}

/** A sticky action bar owns the lane directly above the navigation. */
export function useStickyLayer(root: Ref<HTMLElement | null>): void {
  publishHeight(root, stickyLayerHeight)
}
