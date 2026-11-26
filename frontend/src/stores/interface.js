import { computed, reactive } from 'vue'

const defaults = { material: 'swiss', density: 'comfortable', sound: false, haptics: false }
const options = { material: ['swiss', 'clean', 'glass'], density: ['comfortable', 'compact'] }
const storageKey = 'gb28181-interface'

function readPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey))
    return {
      material: options.material.includes(saved?.material) ? saved.material : defaults.material,
      density: options.density.includes(saved?.density) ? saved.density : defaults.density,
      sound: saved?.sound === true,
      haptics: saved?.haptics === true
    }
  } catch {
    return { ...defaults }
  }
}

const preferences = reactive(readPreferences())
const hapticsAvailable = computed(() =>
  typeof navigator.vibrate === 'function' && window.matchMedia('(pointer: coarse)').matches
)

function applyPreferences() {
  const root = document.documentElement
  root.dataset.material = preferences.material
  root.dataset.density = preferences.density
}

export function setPreference(key, value) {
  if (!Object.hasOwn(defaults, key)) return
  if (Object.hasOwn(options, key) ? !options[key].includes(value) : typeof value !== 'boolean') return
  preferences[key] = value
  applyPreferences()
  try {
    localStorage.setItem(storageKey, JSON.stringify(preferences))
  } catch {
    // The current window still uses the selected appearance.
  }
}

const cues = {
  confirm: [392, 523],
  success: [523, 659, 784],
  error: [349, 262],
  send: [440, 659]
}
let audio

async function playCue(notes) {
  const Audio = window.AudioContext || window.webkitAudioContext
  if (!Audio) return
  audio ||= new Audio()
  if (audio.state === 'suspended') {
    // A context created without a gesture should not queue an audible cue for later.
    if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return
    await audio.resume()
  }
  if (!preferences.sound || audio.state !== 'running') return
  const start = audio.currentTime + 0.008
  notes.forEach((frequency, index) => {
    const at = start + index * 0.045
    const oscillator = audio.createOscillator()
    const envelope = audio.createGain()
    oscillator.frequency.value = frequency
    envelope.gain.setValueAtTime(0.001, at)
    envelope.gain.exponentialRampToValueAtTime(0.045, at + 0.016)
    envelope.gain.exponentialRampToValueAtTime(0.001, at + 0.095)
    oscillator.connect(envelope).connect(audio.destination)
    oscillator.onended = () => envelope.disconnect()
    oscillator.start(at)
    oscillator.stop(at + 0.1)
  })
}

export function feedback(cue) {
  if (!Object.hasOwn(cues, cue)) return
  if (preferences.haptics && hapticsAvailable.value) {
    try { navigator.vibrate(cue === 'error' ? [12, 35, 12] : 12) } catch { /* Optional device feedback. */ }
  }
  if (preferences.sound) void playCue(cues[cue]).catch(() => {})
}

export function initInterface() {
  applyPreferences()
  document.addEventListener('click', (event) => {
    const control = event.target.closest?.('[data-cue]')
    if (control && !control.disabled) feedback(control.dataset.cue)
  })
}

export { hapticsAvailable, preferences }
