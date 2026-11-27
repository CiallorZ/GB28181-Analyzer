import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../src/api/client'
import { useTaskStore } from '../src/stores/task'

vi.mock('../src/api/client', () => ({
  api: { activeTasks: vi.fn() }
}))

let storage

beforeEach(() => {
  setActivePinia(createPinia())
  storage = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn()
  }
  vi.stubGlobal('localStorage', storage)
  api.activeTasks.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('current task persistence', () => {
  it('restores a positive safe integer task ID', () => {
    storage.getItem.mockReturnValue('17')
    expect(useTaskStore().currentTaskId).toBe(17)
  })

  it.each([null, '', 'abc', '0', '-2', '1.5', 'Infinity', '9007199254740992'])(
    'rejects invalid stored ID %s', value => {
      storage.getItem.mockReturnValue(value)
      expect(useTaskStore().currentTaskId).toBeNull()
    })

  it('keeps memory state usable when storage reads and writes fail', () => {
    storage.getItem.mockImplementation(() => { throw new Error('blocked') })
    let store
    expect(() => { store = useTaskStore() }).not.toThrow()
    expect(store.currentTaskId).toBeNull()

    storage.setItem.mockImplementation(() => { throw new Error('blocked') })
    expect(() => store.setCurrent(9)).not.toThrow()
    expect(store.currentTaskId).toBe(9)

    storage.removeItem.mockImplementation(() => { throw new Error('blocked') })
    expect(() => store.setCurrent(null)).not.toThrow()
    expect(store.currentTaskId).toBeNull()
  })
})

describe('active task refresh', () => {
  it('coalesces concurrent calls into a trailing request and ignores stale responses', async () => {
    const resolvers = []
    api.activeTasks.mockImplementation(() => new Promise(resolve => resolvers.push(resolve)))
    const store = useTaskStore()

    const first = store.refreshActive()
    const second = store.refreshActive()
    expect(api.activeTasks).toHaveBeenCalledTimes(1)

    resolvers[0]({ count: 1 })
    await vi.waitFor(() => expect(api.activeTasks).toHaveBeenCalledTimes(2))
    expect(store.activeCount).toBe(0)

    resolvers[1]({ count: 0 })
    await Promise.all([first, second])
    expect(store.activeCount).toBe(0)

    const third = store.refreshActive()
    expect(api.activeTasks).toHaveBeenCalledTimes(3)
    resolvers[2]({ count: 2 })
    await third
    expect(store.activeCount).toBe(2)
  })
})
