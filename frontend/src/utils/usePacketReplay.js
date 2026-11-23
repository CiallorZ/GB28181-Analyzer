import { onMounted, onUnmounted, ref, watch } from 'vue'

// Schematic playback uses fixed steps. Capture timestamps stay on the message rows.
export function usePacketReplay(size, loop = false) {
  const index = ref(0)
  const playing = ref(false)
  const reduced = ref(false)
  let timer, preference
  function pause() {
    clearInterval(timer)
    playing.value = false
  }
  function play() {
    pause()
    if (!size()) return
    if (index.value >= size() - 1) index.value = 0
    playing.value = true
    timer = setInterval(() => {
      if (document.hidden) return
      if (index.value + 1 < size()) index.value++
      else if (loop) index.value = 0
      else pause()
    }, 1500)
  }
  function select(i) { pause(); index.value = i }
  function applyPreference() {
    reduced.value = preference.matches
    if (reduced.value) pause()
  }
  watch(size, () => select(0))
  onMounted(() => {
    preference = matchMedia('(prefers-reduced-motion: reduce)')
    applyPreference()
    preference.addEventListener('change', applyPreference)
    if (loop && !reduced.value) play()
  })
  onUnmounted(() => { pause(); preference?.removeEventListener('change', applyPreference) })
  return { index, playing, reduced, play, pause, select }
}
