/**
 * 图表跟随容器尺寸变化
 *
 * ECharts 只在 init 时量一次容器；侧栏开关、窗口缩放、v-show 切换后
 * 画布会保持旧尺寸（表现为空白或右侧被裁掉）。这里统一挂 resize，
 * 并在视图卸载时解绑。
 */
export function bindChartResize(charts, delay = 120) {
  let timer = null
  const run = () => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      Object.values(charts).forEach((c) => {
        try { c.resize() } catch { /* 已销毁的实例忽略 */ }
      })
    }, delay)
  }
  window.addEventListener('resize', run)
  return () => {
    clearTimeout(timer)
    window.removeEventListener('resize', run)
  }
}
