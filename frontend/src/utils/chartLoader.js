/**
 * ECharts 延迟加载
 *
 * 工作台首屏就要画图，但图表是数据回来之后才需要的：把 echarts 从
 * 同步依赖改成动态 import，首屏 JS 不再包含 176 KB(gzip) 的图表库，
 * 数据到达后再加载。加载结果缓存，后续页面复用同一个 promise。
 */
let pending = null

export function loadECharts() {
  if (!pending) pending = import('./chart').then((m) => m.default)
  return pending
}
