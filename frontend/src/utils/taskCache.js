/**
 * 任务级结果缓存
 *
 * 工作台与各深入页每次挂载都会重取同一批数据；在 /media、/sip 之间来回
 * 切换时，一次就是 6 个并发请求。分析结果只在任务重新分析后才会变化，
 * 所以用「任务 ID + 完成时间」作为版本号：重新分析会更新 completed_at，
 * 版本号随之改变，旧缓存自然失效，不需要调用方手动清。
 *
 * 只缓存已完成任务的结果；分析中/失败的任务不缓存，避免读到半成品。
 */

const MAX_ENTRIES = 32
const entries = new Map()      // key -> value（Map 保持插入顺序，便于 LRU 淘汰）
const inflight = new Map()     // key -> Promise，合并同一 key 的并发请求

function stableStringify(value) {
  if (value == null) return ''
  if (typeof value !== 'object') return String(value)
  const keys = Object.keys(value).sort()
  return '{' + keys.map(k => k + ':' + stableStringify(value[k])).join(',') + '}'
}

/** 任务结果版本号；未完成的任务返回 null（不缓存） */
export function taskRevision(task) {
  if (!task || task.status !== 'completed') return null
  return String(task.completed_at || 'completed')
}

export function cacheKey(taskId, revision, name, params) {
  const suffix = params === undefined ? '' : ':' + stableStringify(params)
  return `${taskId}@${revision}:${name}${suffix}`
}

export function get(key) {
  if (!entries.has(key)) return undefined
  // 命中后移到末尾，保持 LRU 顺序
  const value = entries.get(key)
  entries.delete(key)
  entries.set(key, value)
  return value
}

export function set(key, value) {
  if (entries.has(key)) entries.delete(key)
  entries.set(key, value)
  while (entries.size > MAX_ENTRIES) {
    entries.delete(entries.keys().next().value)
  }
}

/**
 * 读缓存，未命中则调用 loader 并写入。
 * 并发调用同一 key 只发一次请求；loader 失败不写缓存。
 */
export async function cachedLoad(key, loader) {
  const hit = get(key)
  if (hit !== undefined) return hit
  if (inflight.has(key)) return inflight.get(key)
  const pending = Promise.resolve()
    .then(loader)
    .then(value => {
      // clearTask/clearAll may have invalidated this request while it was pending.
      // The identity check also prevents an old request from deleting a newer one.
      if (inflight.get(key) === pending) set(key, value)
      return value
    })
    .finally(() => {
      if (inflight.get(key) === pending) inflight.delete(key)
    })
  inflight.set(key, pending)
  return pending
}

/** 清掉某个任务的所有缓存（删除任务时调用） */
export function clearTask(taskId) {
  const prefix = `${taskId}@`
  for (const key of [...entries.keys()]) {
    if (key.startsWith(prefix)) entries.delete(key)
  }
  for (const key of [...inflight.keys()]) {
    if (key.startsWith(prefix)) inflight.delete(key)
  }
}

export function clearAll() {
  entries.clear()
  inflight.clear()
}

export function size() {
  return entries.size
}
