<script setup>
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { loadECharts } from '../utils/chartLoader'
import { chartBase, chartPalette } from '../utils/chartTheme'
const p = defineProps({
  metrics: Object,
  streams: Array,
  streamId: [Number, String],
  error: Boolean,
  pending: Boolean
})
const emit = defineEmits(['range', 'stream'])
const start = ref(null),
  end = ref(null)
const host = ref(null),
  cursor = ref(null),
  windowRange = ref(null)
const shown = computed(() => p.streams.filter((s) => !p.streamId || s.id === p.streamId))
const synchronized = computed(() => shown.value.length && shown.value.every((s) => s.transport === 'UDP'))
const gapStreams = computed(() => shown.value.filter((s) => s.seq_gap_packets > 0))
const fields = ['bitrate_series', 'jitter_series']
const lines = computed(() =>
  shown.value.flatMap((s, i) =>
    fields.flatMap((key, axis) => {
      const points = p.metrics[s.id]?.[key] || []
      return points.length
        ? [{ name: '流 #' + s.id, index: i, axis, data: points.map((pt) => [pt.t, pt.v]) }]
        : []
    })
  )
)
let instance,
  observer,
  generation = 0
function range(lo, hi) {
  start.value = Number(lo.toFixed(6))
  end.value = Number(hi.toFixed(6))
  windowRange.value = [lo, hi]
  emit('range', synchronized.value ? [lo, hi] : null)
}
function resetRange() {
  start.value = null
  end.value = null
  windowRange.value = null
  emit('range', null)
  draw()
}
function applyRange() {
  if (!Number.isFinite(start.value) || !Number.isFinite(end.value) || start.value >= end.value) return
  range(start.value, end.value)
  draw()
}
async function draw() {
  const seq = ++generation
  await nextTick()
  if (!host.value || !lines.value.length) {
    instance?.dispose()
    instance = null
    return
  }
  const lib = await loadECharts()
  if (seq !== generation || !host.value) return
  if (!instance) {
    instance = lib.init(host.value)
    instance.on('click', (ev) => {
      if (!Array.isArray(ev.value)) return
      cursor.value = ev.value[0]
      const line = lines.value[ev.seriesIndex]
      if (line) emit('stream', shown.value[line.index].id)
    })
    instance.getZr().on('click', (ev) => {
      const pixel = [ev.offsetX, ev.offsetY]
      const grid = [0, 1].find((gridIndex) => instance.containPixel({ gridIndex }, pixel))
      if (grid == null) return
      const [t] = instance.convertFromPixel({ gridIndex: grid }, pixel)
      range(Math.max(0, t - 0.5), t + 0.5)
      draw()
    })
    instance.on('updateAxisPointer', (ev) => {
      if (ev.axesInfo?.length) cursor.value = ev.axesInfo[0].value
    })
    instance.on('datazoom', () => {
      const zoom = instance.getOption().dataZoom[0]
      if (zoom.start === 0 && zoom.end === 100) {
        start.value = null
        end.value = null
        windowRange.value = null
        emit('range', null)
        return
      }
      if (Number.isFinite(zoom.startValue) && Number.isFinite(zoom.endValue))
        range(zoom.startValue, zoom.endValue)
    })
  }
  const c = chartPalette(),
    colors = [c.info, '#b993ff', c.ok, c.warn, c.crit]
  const xs = lines.value.flatMap((l) => l.data.map((pt) => pt[0]))
  const selection = windowRange.value
  const min = xs.reduce((a, b) => Math.min(a, b), selection?.[0] ?? Infinity),
    max = xs.reduce((a, b) => Math.max(a, b), selection?.[1] ?? -Infinity)
  instance.setOption(
    {
      ...chartBase(),
      animation: false,
      legend: {
        type: 'scroll',
        top: 0,
        right: 6,
        width: '78%',
        textStyle: { color: c.text, fontSize: 11 },
        itemHeight: 5,
        itemWidth: 13
      },
      tooltip: { ...chartBase().tooltip, trigger: 'axis', confine: true },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { top: 30, height: '22%', left: 55, right: 17 },
        { top: '56%', height: '19%', left: 55, right: 17 }
      ],
      xAxis: fields.map((_, i) => ({
        type: 'value',
        gridIndex: i,
        min,
        max: max === min ? min + 1 : max,
        axisLabel: { show: i === 1, color: c.dim, fontSize: 11, formatter: (v) => Number(v.toFixed(3)) },
        axisLine: { lineStyle: { color: c.line } },
        splitLine: { show: false }
      })),
      yAxis: ['kbps', 'ms'].map((name, i) => ({
        name,
        type: 'value',
        gridIndex: i,
        splitNumber: 2,
        nameGap: 5,
        nameTextStyle: { color: c.dim },
        axisLabel: { color: c.dim, fontSize: 11 },
        splitLine: { lineStyle: { color: c.line } }
      })),
      dataZoom: [
        {
          type: 'slider',
          ...(selection && { startValue: selection[0], endValue: selection[1] }),
          xAxisIndex: [0, 1],
          bottom: 1,
          height: 14,
          showDetail: false,
          borderColor: c.line,
          fillerColor: c.info + '25'
        }
      ],
      series: lines.value.map((l) => ({
        name: l.name,
        type: 'line',
        xAxisIndex: l.axis,
        yAxisIndex: l.axis,
        data: l.data,
        smooth: false,
        showSymbol: l.data.length < 3,
        lineStyle: { width: 1.5 },
        itemStyle: { color: colors[l.index % colors.length] }
      }))
    },
    true
  )
}
watch([lines, () => p.streamId], () => {
  cursor.value = null
  start.value = null
  end.value = null
  windowRange.value = null
  emit('range', null)
  draw()
})
onMounted(() => {
  draw()
  observer = new ResizeObserver(() => instance?.resize())
  observer.observe(host.value.parentElement)
  window.addEventListener('alma-theme-changed', draw)
})
onUnmounted(() => {
  generation++
  observer?.disconnect()
  instance?.dispose()
  window.removeEventListener('alma-theme-changed', draw)
})
</script>
<template>
  <div class="scope">
    <div class="scope-legend">
      <span>码率 / 抖动</span
      ><small>{{ shown.length }} 路 · {{ synchronized ? '抓包相对时间' : '流观测时间' }} / s</small>
    </div>
    <div ref="host" class="scope-canvas" v-show="lines.length"></div>
    <div class="vacant" v-if="!lines.length">
      {{ error ? '趋势读取失败' : pending ? '正在读取趋势…' : '无可用趋势样本' }}
    </div>
    <details v-if="lines.length" class="range-control">
      <summary>时间范围 / s</summary>
      <form @submit.prevent="applyRange">
        <input type="number" step="any" min="0" required v-model.number="start" aria-label="起点秒" /><span
          >–</span
        ><input
          type="number"
          step="any"
          :min="start"
          required
          v-model.number="end"
          aria-label="终点秒"
        /><button :disabled="!Number.isFinite(start) || !Number.isFinite(end) || start >= end">应用</button><button type="button" @click="resetRange">清除</button>
      </form>
      <small role="status" v-if="Number.isFinite(start) && Number.isFinite(end) && start >= end">终点须晚于起点</small>
    </details>
    <div class="scope-caption">
      <span v-if="cursor != null">游标 {{ Number(cursor).toFixed(3) }} s</span
      ><span v-if="windowRange">选区 {{ windowRange.map((x) => x.toFixed(3)).join(' – ') }} s</span
      ><span>{{ synchronized ? '点击取前后 0.5 s · 选区联动报文与诊断' : '流时序未与视频帧精确对齐' }}</span>
    </div>
    <details class="gap-observations" v-if="gapStreams.length">
      <summary>RTP 序号缺口 · {{ gapStreams.length }} 条流</summary>
      <div v-for="s in gapStreams" :key="s.id">
        <b>#{{ s.id }} · {{ s.transport }} · 缺口 {{ s.seq_gap_packets }} 包</b>
        <p v-for="g in s.extra?.seq_gap_events" :key="g.after_seq">
          流内 {{ g.time }} s · 序号 {{ g.after_seq }} 后缺 {{ g.gap }} 包
          <router-link
            v-if="g.packet > 0"
            :to="{ name: 'packets', query: { task: s.task_id, number: g.packet } }"
            >报文 #{{ g.packet }}</router-link
          >
        </p>
      </div>
    </details>
  </div>
</template>
