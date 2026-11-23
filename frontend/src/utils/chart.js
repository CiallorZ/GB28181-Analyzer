/**
 * ECharts 按需注册
 *
 * 全量 import * as echarts from 'echarts' 会把所有图表类型、坐标系
 * 和渲染器打进主包（压缩后约 1 MB）。这里只注册实际用到的四种图：
 * line / bar / pie / scatter —— 与 views 里的 option 一一对应。
 * 新增图表类型时记得在这里补注册，否则运行时会静默不渲染。
 */
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent, DataZoomComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart, PieChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  CanvasRenderer
])

export default echarts
