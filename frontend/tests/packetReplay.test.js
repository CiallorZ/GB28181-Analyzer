import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { usePacketReplay } from '../src/utils/usePacketReplay'

let unmount, preference, scope
vi.mock('vue', async (original) => ({
  ...await original(),
  onMounted: (callback) => callback(),
  onUnmounted: (callback) => { unmount = callback }
}))

beforeEach(() => {
  vi.useFakeTimers()
  preference = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', () => preference)
  vi.stubGlobal('document', { hidden: false })
  scope = effectScope()
})
afterEach(() => {
  unmount()
  scope.stop()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
const start = (size, loop = false) => scope.run(() => usePacketReplay(size, loop))
const step = () => vi.advanceTimersByTime(1500)

it('示意图自动循环，手动选择暂停', () => {
  const replay = start(() => 2, true)
  step()
  expect(replay.index.value).toBe(1)
  step()
  expect(replay.index.value).toBe(0)
  replay.select(1)
  step()
  expect(replay.playing.value).toBe(false)
  expect(replay.index.value).toBe(1)
})
it('实际信令播放至最后一条停止，可从头再播', () => {
  const replay = start(() => 2)
  expect(replay.playing.value).toBe(false)
  replay.play()
  step()
  step()
  expect(replay.index.value).toBe(1)
  expect(replay.playing.value).toBe(false)
  replay.play()
  expect(replay.index.value).toBe(0)
})
it('减少动态效果时不启动首页动画', () => {
  preference.matches = true
  const replay = start(() => 4, true)
  expect(replay.reduced.value).toBe(true)
  expect(replay.playing.value).toBe(false)
})
it('后台不推进报文，筛选为空后停止', async () => {
  const count = ref(3)
  const replay = start(() => count.value, true)
  document.hidden = true
  step()
  expect(replay.index.value).toBe(0)
  count.value = 0
  await nextTick()
  replay.play()
  expect(replay.playing.value).toBe(false)
})
