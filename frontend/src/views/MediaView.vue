<script setup>
import { ref, shallowRef, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { loadECharts } from '../utils/chartLoader'
import { chartPalette, seriesPalette } from '../utils/chartTheme'
import { bindChartResize } from '../utils/chartResize'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'
import { useTaskStore } from '../stores/task'

const store = useTaskStore()
const streams = shallowRef([])
const err = ref('')
const loading = ref(false)
const activeMetric = ref('bitrate')

const charts = {}
let C = chartPalette()
let PALETTE = seriesPalette()

async function chart(id, opt) {
  const el = document.getElementById(id)
  if (!el) return
  // 图表库是异步加载的，等它回来时容器可能已经因切换任务被移除
  const echarts = await loadECharts()
  if (!el.isConnected) return
  if (charts[id]?.getDom() !== el) {
    charts[id]?.dispose()
    charts[id] = echarts.init(el)
  }
  charts[id].setOption({ animation: false, ...opt }, true)
}

watch(() => store.currentTaskId, async (id, _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  streams.value = []
  err.value = ''
  loading.value = !!id
  if (!id) return
  try {
    const result = await api.mediaQuality(id, controller.signal)
    if (!controller.signal.aborted) streams.value = result.items
  } catch (e) {
    if (!controller.signal.aborted) err.value = e.message
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

function render() {
  C = chartPalette()
  PALETTE = seriesPalette()
  if (activeMetric.value === 'gap') {
    renderGaps()
    return
  }
  const metric = activeMetric.value
  const series = streams.value.flatMap((st, i) => st[metric].length ? [{
    name: st.ssrc == null ? '流 #' + st.id : '0x' + st.ssrc.toString(16),
    type: 'line', smooth: true, showSymbol: false,
    itemStyle: { color: PALETTE[i % PALETTE.length] },
    lineStyle: { width: 2, color: PALETTE[i % PALETTE.length] },
    data: st[metric]
  }] : [])

  chart('c-' + metric, {
    backgroundColor: 'transparent',
    grid: { left: 52, right: 38, top: 26, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: C.tipBg, borderColor: C.tipBorder,
      textStyle: { color: C.tipText, fontSize: 11 }
    },
    legend: {
      top: 0, right: 0, itemWidth: 8, itemHeight: 8,
      textStyle: { color: C.dim, fontSize: 11 },
      data: series.map(s => s.name)
    },
    xAxis: {
      type: 'value', name: '秒',
      nameTextStyle: { color: C.faint, fontSize: 10 },
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 10.5 },
      splitLine: { lineStyle: { color: C.line, type: 'dashed' } }
    },
    yAxis: {
      type: 'value', name: metric === 'bitrate' ? 'kbps' : 'ms',
      nameTextStyle: { color: C.faint, fontSize: 10 },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 10.5 },
      splitLine: { lineStyle: { color: C.line, type: 'dashed' } }
    },
    series: series
  })

}

function renderGaps() {
  // 3. 序号缺口事件时间轴
  const gapPoints = []
  streams.value.forEach((st, i) => {
    const evs = st.gaps
    evs.slice(0, 100).forEach(e => {
      gapPoints.push([e.time, i, e.gap])
    })
  })
  chart('c-gap', {
    backgroundColor: 'transparent',
    grid: { left: 52, right: 38, top: 22, bottom: 26 },
    tooltip: {
      backgroundColor: C.tipBg, borderColor: C.tipBorder,
      textStyle: { color: C.tipText, fontSize: 11 },
      formatter: (p) => {
        const st = streams.value[p.value[1]]
        return `流 0x${st?.ssrc?.toString(16) || '?'}<br/>` +
               `时间 ${p.value[0]}s<br/>缺失 ${p.value[2]} 包`
      }
    },
    xAxis: {
      type: 'value', name: '秒',
      nameTextStyle: { color: C.faint, fontSize: 10 },
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 10.5 },
      splitLine: { lineStyle: { color: C.line, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: streams.value.map((s, i) => '0x' + (s.ssrc ? s.ssrc.toString(16) : i)),
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 10.5, fontFamily: 'monospace' }
    },
    series: [{
      type: 'scatter',
      data: gapPoints,
      symbolSize: (v) => Math.min(16, 5 + (v[2] || 1) * 1.4),
      itemStyle: { color: C.crit, opacity: .8 }
    }]
  })
}

const stats = computed(() => {
  const out = {
    total: streams.value.length,
    totalPackets: 0,
    totalBytes: 0,
    avgBitrate: null,
    maxJitter: null,
    totalGap: 0,
    totalOoo: 0,
    totalDup: 0,
    maxSilence: null,
    duration: null
  }
  if (!streams.value.length) return out
  streams.value.forEach(s => {
    out.totalPackets += s.packet_count || 0
    out.totalBytes += s.byte_count || 0
    out.totalGap += s.seq_gap_packets || 0
    out.totalOoo += s.out_of_order_count || 0
    out.totalDup += s.duplicate_count || 0
    if (s.jitter_max != null) out.maxJitter = Math.max(out.maxJitter || 0, s.jitter_max)
    if (s.max_gap != null) out.maxSilence = Math.max(out.maxSilence || 0, s.max_gap)
    if (s.duration != null) out.duration = Math.max(out.duration || 0, s.duration)
  })
  const brs = streams.value.map(s => s.avg_bitrate).filter(v => v != null)
  if (brs.length) out.avgBitrate = brs.reduce((a, b) => a + b, 0) / brs.length
  return out
})

const fmt = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d)

let unbindResize = null
onMounted(async () => {
  window.addEventListener('alma-theme-changed', render)
  render()
  unbindResize = bindChartResize(charts)
})
onUnmounted(() => {
  window.removeEventListener('alma-theme-changed', render)
  unbindResize?.()
  Object.values(charts).forEach(instance => instance.dispose())
})

// v-show 的图表在隐藏时 init 会得到 0 宽，切回来必须重新量一次
watch([activeMetric, streams, loading], async () => {
  await nextTick()
  render()
  charts['c-' + activeMetric.value]?.resize()
})
</script>

<template>
  <div class="page">
    <PageNav
      title="媒体质量分析"
      :sub="`任务 #${store.currentTaskId || '未选择'} · ${stats.total} 条 RTP 流`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'媒体质量分析'}]">
    </PageNav>

    <div v-if="err" class="err-box mb-12">{{ err }}</div>

    <div v-if="!store.currentTaskId" class="card">
      <div class="empty">尚未选择分析任务</div>
    </div>

    <template v-else>
      <p v-if="loading" role="status">正在读取媒体质量指标…</p>
      <!-- 统计卡 -->
      <div class="kpis mb-12">
        <div class="kpi">
          <div class="kpi-label">RTP 流</div>
          <div class="kpi-value">{{ stats.total }}</div>
          <div class="kpi-sub">{{ stats.totalPackets.toLocaleString() }} 个包</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">平均码率</div>
          <div class="kpi-value" :class="stats.avgBitrate == null ? 'na' : ''">
            {{ stats.avgBitrate != null ? fmt(stats.avgBitrate, 0) : '无媒体' }}
            <span v-if="stats.avgBitrate != null" class="kpi-unit">kbps</span>
          </div>
        </div>
        <div class="kpi" :class="stats.maxJitter > 50 ? 'warning' : 'ok'">
          <div class="kpi-label">峰值抖动</div>
          <div class="kpi-value" :class="stats.maxJitter == null ? 'na' : (stats.maxJitter > 50 ? 'warning' : 'ok')">
            {{ stats.maxJitter != null ? fmt(stats.maxJitter, 2) : '无媒体' }}
            <span v-if="stats.maxJitter != null" class="kpi-unit">ms</span>
          </div>
        </div>
        <div class="kpi" :class="stats.totalGap ? 'critical' : 'ok'">
          <div class="kpi-label">序号缺口</div>
          <div class="kpi-value" :class="stats.totalGap ? 'critical' : 'ok'">
            {{ stats.totalGap }}
          </div>
          <div class="kpi-sub">包（观察值）</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">乱序 / 重复</div>
          <div class="kpi-value">{{ stats.totalOoo }} / {{ stats.totalDup }}</div>
        </div>
        <div class="kpi" :class="stats.maxSilence > 3 ? 'warning' : ''">
          <div class="kpi-label">最大静默</div>
          <div class="kpi-value" :class="stats.maxSilence == null ? 'na' : (stats.maxSilence > 3 ? 'warning' : 'ok')">
            {{ stats.maxSilence != null ? fmt(stats.maxSilence, 2) : '无媒体' }}
            <span v-if="stats.maxSilence != null" class="kpi-unit">s</span>
          </div>
        </div>
      </div>

      <!-- 图表 -->
      <section class="card trend-panel mb-12">
        <header class="trend-head"><h2>媒体传输趋势</h2><div class="seg">
          <button v-for="m in [
              {k:'bitrate',l:'码率'},
              {k:'jitter',l:'抖动'},
              {k:'gap',l:'丢包'}
            ]" :key="m.k" :class="{ on: activeMetric === m.k }" :aria-pressed="activeMetric === m.k"
            @click="activeMetric = m.k">{{ m.l }}</button>
        </div></header>
        <template v-if="streams.length">
          <div v-for="metric in ['bitrate','jitter','gap']" :key="metric" v-show="metric===activeMetric" class="chart-lg" :id="'c-'+metric"></div>
          <p v-if="activeMetric==='gap'" class="hint-inline">点大小表示序号缺失包数。</p>
        </template>
        <div v-else class="empty">{{loading ? '正在读取趋势…' : '无媒体流'}}</div>
      </section>
      <div class="mb-12">
        <div class="card">
          <div class="card-head">流质量对比</div>
          <div class="card-body tight stream-list">
            <table class="tbl" v-if="streams.length">
              <thead>
                <tr>
                  <th>SSRC / 会话</th><th>传输</th><th>包数</th><th>码率</th>
                  <th>抖动</th><th>缺口</th><th>静默</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="st in streams" :key="st.id">
                  <td class="stream-cell"><strong>{{ st.ssrc == null ? '未知 SSRC' : '0x' + st.ssrc.toString(16) }}</strong><router-link v-if="st.session_id" :to="'/sessions/'+st.session_id">会话 #{{st.session_id}} ↗</router-link><small v-else>未关联会话</small></td>
                  <td><span class="proto">{{ st.transport }}</span></td>
                  <td class="num">{{ st.packet_count }}</td>
                  <td class="num">{{ st.avg_bitrate != null ? fmt(st.avg_bitrate, 0) : '—' }}</td>
                  <td class="num" :class="st.jitter_avg > 50 ? 'text-warning' : ''">
                    {{ st.jitter_avg != null ? fmt(st.jitter_avg, 2) : '—' }}
                  </td>
                  <td class="num" :class="st.seq_gap_packets ? 'text-critical' : ''">
                    {{ st.seq_gap_packets }}
                  </td>
                  <td class="num" :class="st.max_gap > 3 ? 'text-warning' : ''">
                    {{ st.max_gap != null ? fmt(st.max_gap, 2) : '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty">
              未发现媒体流
              <div class="hint">
                可能是媒体未经过抓包点，或媒体端口未建立连接
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 说明 -->
      <div class="card">
        <div class="card-head">指标口径说明</div>
        <div class="card-body">
          <div class="notes">
            <div class="note-item">
              <b>序号缺口 ≠ 网络丢包</b>
              <p>缺口是"在抓包点观察到的序号不连续"。可能来自真实丢包、
                抓包缓冲区溢出、或抓包点位于会话中途。
                <span class="text-critical">TCP 承载时尤其不能直接判定为丢包</span>——
                TCP 本身可靠，缺口通常意味着抓包不完整。</p>
            </div>
            <div class="note-item">
              <b>抖动按 RFC 3550 计算</b>
              <p>J(i) = J(i-1) + (|D(i-1,i)| - J(i-1)) / 16，
                其中 D 是传输时间差。国标 PS 流时钟频率为 90000。
                抖动只反映到达间隔变化，不代表画面质量。</p>
            </div>
            <div class="note-item">
              <b>码率是网络层统计</b>
              <p>这里统计的是抓包点观察到的 RTP 字节速率，
                <span class="text-warning">不等于编码器输出的视频码率</span>。
                两者差异来自封装开销、重传与抓包丢失。</p>
            </div>
            <div class="note-item">
              <b>静默可能是正常的</b>
              <p>静止画面的监控流码率极低，长间隔可能是正常可变码率行为。
                需结合诊断规则与其他指标综合判断。</p>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.h1 { font-size: 19px; font-weight: 600; }
.sub { font-size: 12px; color: var(--text-3); margin-top: 3px; }
.trend-panel {overflow:hidden}
.trend-head {display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 18px;background:var(--surface-2);border-bottom:1px solid var(--line)}
.trend-head h2 {font-size:16px;font-weight:650}
.chart-lg {height:clamp(220px,30vh,350px);margin:12px 8px 4px}
.trend-panel .hint-inline {padding:0 18px 12px}
.stream-list {overflow:auto;max-height:460px}
.stream-list th {position:sticky;top:0;background:var(--surface-2)}

.hint-inline { font-size: 11.5px; color: var(--text-4); font-weight: 400; }

.notes { display: flex; flex-direction: column; gap: 13px; }
.note-item { padding-left: 11px; border-left: 2px solid var(--line-2); }
.note-item b {
  display: block; font-size: 12.5px;
  color: var(--text); font-weight: 600; margin-bottom: 4px;
}
.note-item p {
  font-size: 12px; color: var(--text-3);
  line-height: 1.75;
}
.stream-cell strong{display:block;font:600 12px var(--font-mono)}.stream-cell small,.stream-cell a{font-size:11px}.stream-cell small{color:var(--text-3)}
</style>
