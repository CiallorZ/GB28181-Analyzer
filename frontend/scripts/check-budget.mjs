/**
 * 首屏 JS 预算检查
 *
 * 只统计入口的「静态」依赖图：动态 import 的 chunk（图表库）不在首屏关键路径上。
 * 阈值 110 KB（gzip）——当前约 94 KB，留出余量；echarts 回到静态依赖会立刻超标。
 */
import { readFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const budget = 110 * 1024
const manifest = JSON.parse(readFileSync(join(dist, '.vite/manifest.json'), 'utf8'))

const entryKey = Object.keys(manifest).find(
  (k) => manifest[k].isEntry && k.endsWith('.html')
)
if (!entryKey) {
  console.error('manifest 中没有 HTML 入口')
  process.exit(1)
}

const seen = new Set()
const walk = (key) => {
  if (seen.has(key) || !manifest[key]) return
  seen.add(key)
  for (const dep of manifest[key].imports || []) walk(dep)
}
walk(entryKey)

let total = 0
for (const key of seen) {
  const file = manifest[key].file
  const size = gzipSync(readFileSync(join(dist, file))).length
  total += size
  console.log(`  ${file.padEnd(44)} ${(size / 1024).toFixed(1)} KB`)
}
console.log(`首屏同步 JS 合计 ${(total / 1024).toFixed(1)} KB（预算 ${(budget / 1024).toFixed(0)} KB）`)

if (total > budget) {
  console.error('首屏 JS 超出预算：把图表库或新依赖挪到动态 import')
  process.exit(1)
}
