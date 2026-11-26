import { describe, expect, it, vi } from 'vitest'
import {
  cacheKey, cachedLoad, clearAll, clearTask, get, set, size, taskRevision
} from '../src/utils/taskCache'

describe('taskCache', () => {
  it('未完成的任务不产生版本号', () => {
    expect(taskRevision(null)).toBeNull()
    expect(taskRevision({ status: 'analyzing', completed_at: 'x' })).toBeNull()
    expect(taskRevision({ status: 'completed', completed_at: '2026-11-26T00:00:00' }))
      .toBe('2026-11-26T00:00:00')
  })

  it('版本号变化即换 key，重新分析不会读到旧结果', () => {
    const a = cacheKey(7, taskRevision({ status: 'completed', completed_at: 'A' }), 'overview')
    const b = cacheKey(7, taskRevision({ status: 'completed', completed_at: 'B' }), 'overview')
    expect(a).not.toBe(b)
  })

  it('参数顺序不同但内容相同，得到同一个 key', () => {
    expect(cacheKey(1, 'r', 'sessions', { page: 1, size: 2 }))
      .toBe(cacheKey(1, 'r', 'sessions', { size: 2, page: 1 }))
    expect(cacheKey(1, 'r', 'sessions', { page: 1 }))
      .not.toBe(cacheKey(1, 'r', 'sessions', { page: 2 }))
  })

  it('cachedLoad 命中后不再调用 loader', async () => {
    clearAll()
    const loader = vi.fn().mockResolvedValue({ items: [1] })
    const key = cacheKey(1, 'r', 'overview')

    expect(await cachedLoad(key, loader)).toEqual({ items: [1] })
    expect(await cachedLoad(key, loader)).toEqual({ items: [1] })
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('并发请求同一个 key 只发一次', async () => {
    clearAll()
    const loader = vi.fn().mockResolvedValue(42)
    const key = cacheKey(2, 'r', 'media')

    const [a, b] = await Promise.all([cachedLoad(key, loader), cachedLoad(key, loader)])

    expect([a, b]).toEqual([42, 42])
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('loader 失败不写缓存，下一次会重试', async () => {
    clearAll()
    const key = cacheKey(3, 'r', 'packets')
    const failing = vi.fn().mockRejectedValue(new Error('boom'))

    await expect(cachedLoad(key, failing)).rejects.toThrow('boom')
    expect(get(key)).toBeUndefined()

    const ok = vi.fn().mockResolvedValue('done')
    expect(await cachedLoad(key, ok)).toBe('done')
  })

  it('clearTask 只清该任务，其它任务保留', () => {
    clearAll()
    set(cacheKey(1, 'r', 'a'), 'x')
    set(cacheKey(2, 'r', 'a'), 'y')

    clearTask(1)

    expect(get(cacheKey(1, 'r', 'a'))).toBeUndefined()
    expect(get(cacheKey(2, 'r', 'a'))).toBe('y')
  })

  it('条目数超过上限时淘汰最久未使用的', () => {
    clearAll()
    for (let i = 0; i < 40; i++) set('k' + i, i)
    expect(size()).toBe(32)
    expect(get('k0')).toBeUndefined()
    expect(get('k39')).toBe(39)
  })

  it('读取会把条目移到 LRU 末尾，从而避免被淘汰', () => {
    clearAll()
    for (let i = 0; i < 32; i++) set('k' + i, i)
    get('k0')                 // k0 变成最近使用
    set('k-new', 'new')       // 淘汰最久未使用的 k1
    expect(get('k0')).toBe(0)
    expect(get('k1')).toBeUndefined()
  })
})
