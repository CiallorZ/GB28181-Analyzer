// Animate a change of evidence without replacing the DOM, losing focus or replaying video.
const active = new WeakMap()

export const panelChange = {
  updated(element, { value, oldValue }) {
    if (value === oldValue) return
    active.get(element)?.cancel()
    if (!element.getClientRects().length || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const animation = element.animate([
      { opacity: 0.7, transform: 'translateY(3px)' },
      { opacity: 1, transform: 'translateY(0)' }
    ], { duration: 180, easing: 'cubic-bezier(.2,.8,.2,1)' })
    active.set(element, animation)
  },
  beforeUnmount(element) {
    active.get(element)?.cancel()
    active.delete(element)
  }
}
