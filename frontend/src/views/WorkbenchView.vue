<script setup>
/**
 * 工作台：单入口 + 瀑布式分析结果
 *
 * 设计思路：
 *   上传 → 自动分析 → 结果按"信令 → 媒体 → 编码 → 诊断 → 报文"逐层展开，
 *   每节可折叠、可跳转，滚动时自动高亮当前节（滚动叙事）。
 */
import { defineAsyncComponent, shallowRef, ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import BackButton from '../components/BackButton.vue'
import { useRoute, useRouter } from 'vue-router'
import { loadECharts } from '../utils/chartLoader'
import { chartPalette } from '../utils/chartTheme'
import { bindChartResize } from '../utils/chartResize'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import VideoPlayer from '../components/VideoPlayer.vue'
import AiSummarySection from '../components/AiSummarySection.vue'
import CaptureIntake from '../components/CaptureIntake.vue'
import { feedback } from '../stores/interface'
import CaptureEvidence from '../components/CaptureEvidence.vue'
import CaptureFlow from '../components/CaptureFlow.vue'

const PrecisionWorkspace = defineAsyncComponent(() => import('../components/PrecisionWorkspace.vue'))
const expandedReport = ref(false)
const router = useRouter()
const route = useRoute()
const store = useTaskStore()

const task = ref(null)
const overview = ref(null)
const sessions = ref([])
const diagnostics = ref([])
const streams = ref([])
const mediaStats = ref(null)
const TREND_LIMIT = 12
const metrics = shallowRef({})
const metricsError = ref(false)
const metricsPending = ref(false)
const packets = ref([])
const packetTotal = ref(0)

const uploading = ref(false)
const uploadPct = ref(0)
const err = ref('')
const loadingResults = ref(false)
const startFailure = ref(null)
const busyStage = ref('')
const busyPct = ref(0)

const openSections = ref({
  kpi: true, signal: true, media: true,
  codec: true, diag: true, packet: true
})
const activeSection = ref('kpi')
const charts = {}
let C = chartPalette()

/* ---------------- 主题色读取（图表跟随明暗） ---------------- */
function themeColors() {
  return chartPalette()
}

// 报告由浏览器直接下载，不经 axios，文件名交给后端 Content-Disposition
async function toggleReport() {
  expandedReport.value = !expandedReport.value
  await nextTick()
  if (expandedReport.value) {
    setupScrollSpy()
    renderCharts()
    document.querySelector('.spy')?.scrollIntoView({block:'start'})
  } else {
    onThemeChange()
  }
}

function reportUrl(format) {
  return `/api/v1/tasks/${task.value?.id}/report?format=${format}`
}

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
  charts[id].setOption(opt, true)
}

function baseGrid(extra = {}) {
  const t = themeColors()
  return {
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    backgroundColor: 'transparent',
    textStyle: { color: t.text, fontSize: 11 },
    tooltip: {
      backgroundColor: t.tipBg,
      borderColor: t.tipBorder,
      borderWidth: 1,
      textStyle: { color: t.tipText, fontSize: 11.5 },
      extraCssText: 'box-shadow:0 6px 24px rgba(0,0,0,.22);border-radius:8px;'
    },
    ...extra
  }
}

function axisCommon() {
  const t = themeColors()
  return {
    axisLine: { lineStyle: { color: t.line } },
    axisTick: { show: false },
    axisLabel: { color: t.dim, fontSize: 10.5 }
  }
}
function splitCommon() {
  const t = themeColors()
  return { splitLine: { lineStyle: { color: t.line, type: 'dashed' } } }
}

/* ---------------- 数据加载 ---------------- */
let loadSeq = 0
async function loadAll() {
  if (!store.currentTaskId) return
  const seq = ++loadSeq
  const tid = store.currentTaskId
  const stale = () => seq !== loadSeq || tid !== store.currentTaskId
  loadingResults.value = true
  err.value = ''
  metricsError.value = false
  try {
    const current = await store.loadTask(tid)
    if (stale()) return
    task.value = current
    if (current.status !== 'completed') return
    const [ov, ss, dg, pk, media, stats] = await Promise.all([
      api.overview(tid),
      api.sessions(tid, { page_size: 30 }),
      api.diagnostics(tid, { page_size: 40 }),
      api.packets(tid, { page_size: 8 }),
      api.taskMedia(tid),
      api.taskMediaStats(tid).catch(() => null)
    ])
    if (stale()) return
    overview.value = ov
    sessions.value = ss.items
    diagnostics.value = dg.items
    packets.value = pk.items
    packetTotal.value = pk.total
    streams.value = media.items
    mediaStats.value = stats
    metrics.value = {}
    loadingResults.value = false

    await nextTick()
    if (stale()) return
    renderCharts()
    const ids = media.items.slice(0, TREND_LIMIT).map(stream => stream.id)
    if (ids.length) {
      metricsPending.value = true
      try {
        const result = await api.taskMetrics(tid, ids)
        if (stale()) return
        metrics.value = Object.fromEntries(result.items.map(item => [item.stream_id, item]))
        renderMediaCharts()
      } catch {
        if (!stale()) metricsError.value = true
      } finally { if (!stale()) metricsPending.value = false }
    }
  } catch (error) {
    if (!stale()) err.value = error.message
  } finally {
    if (!stale()) loadingResults.value = false
  }
}

function renderCharts() {
  const ov = overview.value
  if (!ov || !expandedReport.value) return
  const s = ov.summary || {}
  C = themeColors()
  const t = C

  /* --- 1. 业务分布环形 --- */
  const md = ov.method_distribution || {}
  const biz = Object.entries(md).map(([k, v]) => ({ name: k, value: v }))
    .sort((a, b) => b.value - a.value)
  const bizTotal = biz.reduce((a, b) => a + b.value, 0)

  chart('c-biz', baseGrid({
    tooltip: { ...baseGrid().tooltip, trigger: 'item' },
    legend: {
      orient: 'vertical', right: 8, top: 'center',
      itemWidth: 8, itemHeight: 8, itemGap: 10,
      textStyle: { color: t.text, fontSize: 11 },
      formatter: (n) => {
        const it = biz.find(d => d.name === n)
        return it ? `${n}  ${(it.value / (bizTotal || 1) * 100).toFixed(0)}%` : n
      }
    },
    series: [{
      type: 'pie', radius: ['52%', '76%'], center: ['27%', '50%'],
      itemStyle: { borderColor: t.surface, borderWidth: 3 },
      label: {
        show: true, position: 'center',
        formatter: () => `{n|${bizTotal}}\n{l|报文}`,
        rich: {
          n: { fontSize: 22, fontWeight: 700, color: t.tipText, lineHeight: 26 },
          l: { fontSize: 10.5, color: t.dim }
        }
      },
      data: biz,
      color: [C.ds, C.info, C.dim, C.ok, '#A371F7', C.warn]
    }]
  }))

  /* --- 2. 响应码 --- */
  const cd = ov.code_distribution || {}
  const codes = Object.entries(cd).sort((a, b) => b[1] - a[1]).slice(0, 7)
  chart('c-code', baseGrid({
    grid: { left: 66, right: 46, top: 10, bottom: 10 },
    tooltip: { ...baseGrid().tooltip, trigger: 'axis',
               axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: codes.map(c => c[0]).reverse(),
      ...axisCommon(),
      axisLabel: { color: t.text, fontSize: 10.5, fontFamily: 'monospace' }
    },
    series: [{
      type: 'bar',
      data: codes.map(c => ({
        value: c[1],
        itemStyle: {
          color: c[0].startsWith('2') ? C.ok
            : /^[456]/.test(c[0]) ? C.crit
            : c[0].startsWith('1') ? C.info : C.warn,
          borderRadius: [0, 4, 4, 0]
        }
      })).reverse(),
      barWidth: 13,
      label: { show: true, position: 'right', color: t.text, fontSize: 10.5 }
    }]
  }))

  /* --- 3. 会话状态 --- */
  const sigD = ov.signal_distribution || {}
  const medD = ov.media_distribution || {}
  const total = s.session_count || 0
  const statuses = [
    ['成功 / 已接收', sigD.success, medD.received, C.ok],
    ['失败 / 无媒体', sigD.failed, medD.no_media, C.crit],
    ['不完整 / 不可解码', sigD.incomplete, medD.undecodable, C.warn],
    ['未知', sigD.unknown, medD.unknown, t.dim]
  ]
  if (total) chart('c-state', baseGrid({
    grid: { left: 59, right: 20, top: 32, bottom: 26 },
    tooltip: { ...baseGrid().tooltip, trigger: 'item' },
    legend: { top: 0, textStyle: { color: t.text, fontSize: 10.5 } },
    xAxis: { type: 'value', minInterval: 1, max: total, ...axisCommon(), ...splitCommon() },
    yAxis: { type: 'category', inverse: true, data: ['信令', '媒体'], ...axisCommon() },
    series: statuses.map(([name, signal, media, color]) => ({
      name, type: 'bar', stack: 'status', barMaxWidth: 18,
      itemStyle: { color }, data: [signal || 0, media || 0]
    }))
  }))

  renderMediaCharts()
}

function renderMediaCharts() {
  if (!streams.value.length) return
  const t = themeColors()
  /* --- 4. 码率趋势 --- */
  const PALETTE = [C.brand, C.info, C.ok, C.warn, '#9b59f0', C.ds]
  const trendStreams = streams.value.slice(0, TREND_LIMIT)
  const streamLabel = st => `#${st.id}${st.ssrc == null ? '' : ' · 0x' + st.ssrc.toString(16)}`
  const brSeries = trendStreams.map((st, i) => {
    const m = metrics.value[st.id]
    if (!m?.bitrate_series?.length) return null
    return {
      name: streamLabel(st),
      type: 'line', smooth: false, showSymbol: false,
      lineStyle: { width: 1.8, color: PALETTE[i % PALETTE.length] },
      // 面积用单层低透明度填充：渐变在暗色下会把网格线压暗，也不承载信息
      areaStyle: { color: PALETTE[i % PALETTE.length] + '18' },
      data: m.bitrate_series.map(p => [p.t, p.v])
    }
  }).filter(Boolean)

  chart('c-bitrate', baseGrid({
    grid: { left: 56, right: 20, top: 34, bottom: 30 },
    legend: {
      top: 0, right: 0, itemWidth: 8, itemHeight: 8, itemGap: 12,
      textStyle: { color: t.dim, fontSize: 10.5 },
      data: brSeries.map(x => x.name)
    },
    tooltip: { ...baseGrid().tooltip, trigger: 'axis' },
    xAxis: {
      type: 'value', name: '秒', nameTextStyle: { color: t.dim, fontSize: 10.5 },
      ...axisCommon(), ...splitCommon()
    },
    yAxis: {
      type: 'value', name: 'kbps', nameTextStyle: { color: t.dim, fontSize: 10.5 },
      ...axisCommon(), ...splitCommon(), axisLine: { show: false }
    },
    series: brSeries
  }))

  /* --- 5. 抖动趋势 --- */
  const jSeries = trendStreams.map((st, i) => {
    const m = metrics.value[st.id]
    if (!m?.jitter_series?.length) return null
    return {
      name: streamLabel(st),
      type: 'line', smooth: false, showSymbol: false,
      lineStyle: { width: 1.8, color: PALETTE[i % PALETTE.length] },
      data: m.jitter_series.map(p => [p.t, p.v])
    }
  }).filter(Boolean)

  chart('c-jitter', baseGrid({
    grid: { left: 56, right: 20, top: 34, bottom: 30 },
    legend: {
      top: 0, right: 0, itemWidth: 8, itemHeight: 8, itemGap: 12,
      textStyle: { color: t.dim, fontSize: 10.5 },
      data: jSeries.map(x => x.name)
    },
    tooltip: { ...baseGrid().tooltip, trigger: 'axis' },
    xAxis: {
      type: 'value', name: '秒', nameTextStyle: { color: t.dim, fontSize: 10.5 },
      ...axisCommon(), ...splitCommon()
    },
    yAxis: {
      type: 'value', name: 'ms', nameTextStyle: { color: t.dim, fontSize: 10.5 },
      ...axisCommon(), ...splitCommon(), axisLine: { show: false }
    },
    series: jSeries
  }))
}

/* ---------------- 上传 ---------------- */
async function handleFile(f) {
  if (!f || uploading.value) return
  if (!/\.(pcap|pcapng|cap)$/i.test(f.name) || !f.size) {
    err.value = '请选择非空的 .pcap、.pcapng 或 .cap 抓包文件。'
    return
  }
  err.value = ''
  uploading.value = true
  uploadPct.value = 0
  const uploadRoute = router.currentRoute.value
  try {
    const res = await api.upload(f, p => { uploadPct.value = p })
    startFailure.value = null
    try {
      await api.analyze(res.task_id)
    } catch (error) {
      startFailure.value = { id: res.task_id, message: error.message }
    }
    if (router.currentRoute.value === uploadRoute) {
      await router.push({ name: 'task', params: { id: res.task_id } })
    }
  } catch (e) {
    err.value = e.message
  } finally {
    uploading.value = false
  }
}

const loadingSample = ref(false)
async function loadSample() {
  if (uploading.value || loadingSample.value) return
  loadingSample.value = true
  err.value = ''
  try {
    const response = await fetch('/samples/gb28181-demo.pcap')
    if (!response.ok) throw new Error('示例抓包暂时无法读取。')
    await handleFile(new File([await response.blob()], 'gb28181-demo.pcap'))
  } catch (error) {
    err.value = error.message
  } finally {
    loadingSample.value = false
  }
}

let pollTimer = null
let pollGeneration = 0
let unbindResize = null
function startPoll() {
  stopPoll()
  const generation = pollGeneration
  const tid = store.currentTaskId
  const active = () => generation === pollGeneration && tid === store.currentTaskId
  async function poll() {
    try {
      const current = await store.loadTask(tid)
      if (!active()) return
      if (err.value.startsWith('暂时无法读取分析进度')) err.value = ''
      task.value = current
      busyStage.value = task.value.stage || ''
      busyPct.value = task.value.progress || 0
      if (!['pending', 'analyzing'].includes(task.value.status)) {
        stopPoll()
        if (task.value.status === 'completed') {
          feedback('success')
          await loadAll()
        } else if (task.value.status === 'failed') {
          feedback('error')
        }
      }
    } catch {
      if (active()) err.value = '暂时无法读取分析进度，正在重试…'
    }
    if (active()) pollTimer = setTimeout(poll, 1000)
  }
  pollTimer = setTimeout(poll, 750)
}
function stopPoll() {
  pollGeneration++
  clearTimeout(pollTimer)
  pollTimer = null
}

const reanalyzing = ref(false)
const cancelling = ref(false)
async function cancelAnalysis() {
  if (cancelling.value) return
  const tid = task.value.id
  cancelling.value = true
  err.value = ''
  try {
    await api.cancel(tid)
    if (tid === store.currentTaskId) await loadAll()
  } catch (error) {
    err.value = error.message
  } finally {
    cancelling.value = false
  }
}

async function reanalyze() {
  if (!store.currentTaskId || reanalyzing.value) return
  const tid = store.currentTaskId
  reanalyzing.value = true
  err.value = ''
  try {
    await api.analyze(tid)
    if (tid !== store.currentTaskId) return
    startFailure.value = null
    const updated = await store.loadTask(tid)
    if (tid !== store.currentTaskId) return
    task.value = updated
    if (updated.status === 'completed') await loadAll()
    else startPoll()
  } catch (e) {
    err.value = e.message
  } finally {
    reanalyzing.value = false
  }
}

function clearResults() {
  stopPoll()
  metricsPending.value = false
  expandedReport.value = false
  loadSeq++
  task.value = null
  overview.value = null
  sessions.value = []
  diagnostics.value = []
  streams.value = []
  packets.value = []
  packetTotal.value = 0
  mediaStats.value = null
  busyStage.value = ''
  busyPct.value = 0
  metrics.value = {}
  err.value = ''
  loadingResults.value = false
  activeSection.value = 'kpi'
  for (const id of Object.keys(charts)) {
    charts[id].dispose()
    delete charts[id]
  }
}

function reset() {
  if (router.currentRoute.value.name === 'task') router.push('/')
}

// 分析步骤（与后端 stage 百分比对齐）
const ANALYSIS_STEPS = [
  { label: '读取文件信息', pct: 5 },
  { label: '建立报文索引', pct: 15 },
  { label: '解析 SIP 信令', pct: 30 },
  { label: '重建点播会话', pct: 45 },
  { label: '分析 RTP 媒体', pct: 60 },
  { label: 'PS/ES 解封装', pct: 75 },
  { label: '执行诊断', pct: 85 },
  { label: '生成汇总', pct: 95 }
]

/* ---------------- 派生数据 ---------------- */
const summary = computed(() => overview.value?.summary || {})
const diagTotal = computed(() => {
  const d = summary.value.diagnostics || {}
  return (d.critical || 0) + (d.warning || 0) + (d.info || 0) + (d.unknown || 0)
})
// 异常的严重度决定颜色：只有警告时不该显示成故障红
const diagTone = computed(() => {
  const d = summary.value.diagnostics || {}
  if (d.critical) return 'critical'
  if (d.warning) return 'warning'
  return 'ok'
})
// 首包 1.5s 内视为正常，超出才提示，避免把 0.240s 也染成警告色
const latencyTone = computed(() => {
  const v = summary.value.avg_first_media_latency
  if (v == null) return 'na'
  return v > 1.5 ? 'warning' : ''
})

// 编码信息汇总（从流的 extra.ps 里取）
const codecList = computed(() =>
  streams.value.map(st => ({
    id: st.id,
    ssrc: st.ssrc,
    codec: st.codec,
    width: st.width,
    height: st.height,
    frameCount: st.frame_count,
    keyframeCount: st.keyframe_count,
    transport: st.transport,
    ps: st.extra?.ps || null,
    psSampled: Boolean(st.extra?.ps_sampled)
  })).filter(x => x.codec || x.ps)
)

const codecSummary = computed(() => {
  const set = new Set()
  let res = ''
  codecList.value.forEach(x => {
    if (x.codec) set.add(x.codec)
    if (x.width && x.height && !res) res = `${x.width}×${x.height}`
  })
  return {
    codecs: [...set],
    resolution: res || null,
    totalFrames: codecList.value.every(x => x.frameCount != null) ? codecList.value.reduce((n, x) => n + x.frameCount, 0) : null,
    totalKeyframes: codecList.value.every(x => x.keyframeCount != null) ? codecList.value.reduce((n, x) => n + x.keyframeCount, 0) : null
  }
})

// 各板块是否有内容 —— 空板块自动隐藏（不再显示"挤在一起"的空框）
const hasSignal = computed(() => sessions.value.length > 0)
const hasMedia = computed(() => streams.value.length > 0)
const hasCodec = computed(() => codecList.value.length > 0)
const hasDiag = computed(() => diagnostics.value.length > 0)
const hasPacket = computed(() => packets.value.length > 0)

// 可播放的视频流（重建成功的），按包数降序，多的更有内容
const playableStreams = computed(() =>
  streams.value
    .filter(st => st.extra?.rebuild?.ok && st.rebuilt_path)
    .sort((a, b) => (b.packet_count || 0) - (a.packet_count || 0)))

// 视频展示数量（流太多时先显示前 N 个，可展开）
const videoLimit = ref(8)
const showAllVideos = ref(false)
const visibleVideos = computed(() =>
  showAllVideos.value ? playableStreams.value
                      : playableStreams.value.slice(0, videoLimit.value))

// 动态编号：只给可见板块编号
const secNums = computed(() => {
  const map = {}
  let n = 1
  map.kpi = n++
  if (hasSignal.value) map.signal = n++
  if (hasMedia.value) map.media = n++
  if (hasCodec.value) map.codec = n++
  if (hasDiag.value) map.diag = n++
  if (hasPacket.value) map.packet = n++
  map.ai = n
  return map
})

const spyList = computed(() => {
  const out = [{ k: 'kpi', l: '总览' }]
  if (hasSignal.value) out.push({ k: 'signal', l: '信令' })
  if (hasMedia.value) out.push({ k: 'media', l: '媒体' })
  if (hasCodec.value) out.push({ k: 'codec', l: '编码' })
  if (hasDiag.value) out.push({ k: 'diag', l: '诊断' })
  if (hasPacket.value) out.push({ k: 'packet', l: '报文' })
  out.push({ k: 'ai', l: 'AI 分析' })
  return out
})

const EV = { confirmed: '已确认', suspected: '疑似', insufficient: '证据不足' }
const EV_CLS = { confirmed: 'ok', suspected: 'warning', insufficient: 'unknown' }
const SEV_CLS = { critical: 'critical', warning: 'warning', info: 'info', unknown: 'unknown' }
const priorityFindings = computed(() => diagnostics.value
  .filter(d => d.severity === 'critical' || d.severity === 'warning').slice(0, 3))
const flowStages = computed(() => {
  const s = summary.value
  const d = s.diagnostics || {}
  const linked = streams.value.filter(stream => stream.session_id != null).length
  return [
    { key: 'signal', icon: 'signal', label: '信令会话', value: s.session_count != null ? `${s.session_count} 个会话` : '暂无数据', detail: 'SIP / SDP', available: hasSignal.value },
    { key: 'media', icon: 'wave', label: '媒体传输', value: `${streams.value.length} 条流`, detail: `已关联 ${linked} · 未关联 ${streams.value.length - linked}`, available: hasMedia.value },
    { key: 'video', icon: 'monitor', label: '视频重建', value: `${playableStreams.value.length} 条可预览`, detail: '本机生成的 MP4', available: hasMedia.value },
    { key: 'diag', icon: 'file', label: '诊断事件', value: `${diagTotal.value} 条事件`, detail: `${d.critical ?? 0} 严重 · ${d.warning ?? 0} 警告 · ${d.info ?? 0} 提示`, available: hasDiag.value, tone: d.critical ? 'critical' : d.warning ? 'warning' : '' }
  ]
})

const fmt = (v, d = 2) => v == null ? null : Number(v).toFixed(d)

function toggle(k) { openSections.value[k] = !openSections.value[k] }
function goSession(id) { router.push(`/sessions/${id}`) }
function goPacket(num) {
  router.push({ name: 'packets', query: { number: num } })
}

/* ---------------- 滚动叙事：高亮当前节 ---------------- */
const SECTION_IDS = ['sec-kpi', 'sec-ai', 'sec-signal', 'sec-media', 'sec-codec', 'sec-diag', 'sec-packet']
let scrollObs = null

function setupScrollSpy() {
  if (scrollObs) scrollObs.disconnect()
  const opts = { rootMargin: '-30% 0px -55% 0px', threshold: 0 }
  scrollObs = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        activeSection.value = e.target.id.replace('sec-', '')
      }
    })
  }, opts)
  nextTick(() => {
    SECTION_IDS.forEach(id => {
      const el = document.getElementById(id)
      if (el) scrollObs.observe(el)
    })
  })
}

async function scrollTo(sec) {
  const section = sec === 'video' ? 'media' : sec
  if (section in openSections.value && !openSections.value[section]) {
    openSections.value[section] = true
    await nextTick()
  }
  const el = document.getElementById('sec-' + sec)
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (el) {
    activeSection.value = section
    el.scrollIntoView({ behavior: motion ? 'auto' : 'smooth', block: 'start' })
  }
}

// 主题切换后重绘图表
function onThemeChange() {
  Object.keys(charts).forEach(k => {
    charts[k]?.dispose()
    delete charts[k]
  })
  nextTick(renderCharts)
}

onMounted(() => {
  window.addEventListener('alma-theme-changed', onThemeChange)
  unbindResize = bindChartResize(charts)
})
onUnmounted(() => {
  clearResults()
  unbindResize?.()
  scrollObs?.disconnect()
  window.removeEventListener('alma-theme-changed', onThemeChange)
})
watch(() => route.name === 'task' ? Number(route.params.id) : null, async (tid) => {
  clearResults()
  if (!tid) return
  await loadAll()
  if (tid === store.currentTaskId &&
      (task.value?.status === 'analyzing' || task.value?.stage === '排队中')) startPoll()
}, { immediate: true })
watch(spyList, setupScrollSpy, { flush: 'post' })
watch(openSections, () => nextTick(renderCharts), { deep: true })
</script>

<template>
  <div class="page" :class="{ workstation: task?.status === 'completed' }">
    <nav v-if="route.name === 'task'" class="task-breadcrumb" aria-label="任务导航">
      <BackButton fallback="/tasks" /><router-link to="/">工作台</router-link><span>/</span>
      <router-link to="/tasks">历史任务</router-link><span>/</span><strong>任务 #{{ route.params.id }}</strong>
    </nav>
    <div v-if="!task && loadingResults" class="fail-wrap" role="status">正在读取任务…</div>
    <div v-else-if="!task && route.name === 'task'" class="fail-wrap">
      <p class="err-box" role="alert">{{ err || '无法读取任务' }}</p>
      <button class="btn" @click="loadAll">重试</button>
    </div>
    <CaptureIntake v-else-if="!task" :busy="uploading || loadingSample" :progress="uploadPct" :error="err"
                   @recorded="id => router.push({name: 'task', params:{id}})" @file="handleFile" @sample="loadSample" />

    <div v-else-if="task.status === 'pending' && task.stage !== '排队中'" class="fail-wrap">
      <div class="info-box">
        <strong>抓包已导入，等待分析</strong>
        <div class="mt-10">{{ task.file?.filename || task.name }}</div>
      </div>
      <p v-if="err || startFailure?.id === task.id" class="err-box mt-14" role="alert">
        {{ err || startFailure.message }}
      </p>
      <button class="btn mt-14" :disabled="reanalyzing" @click="reanalyze">开始分析</button>
      <button class="btn mt-14" @click="reset">返回工作台</button>
    </div>

    <!-- ==================== 分析中 ==================== -->
    <div v-else-if="['pending', 'analyzing'].includes(task.status)" class="analyzing-wrap">
      <div class="an-card">
        <div class="an-ring" role="progressbar" aria-label="分析进度" :aria-valuenow="busyPct || task.progress || 0">
          <svg viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none"
                    stroke="var(--line)" stroke-width="6"/>
            <circle cx="50" cy="50" r="42" fill="none"
                    stroke="var(--info)" stroke-width="6"
                    stroke-linecap="round"
                    :stroke-dasharray="`${264 * (busyPct || task.progress) / 100} 264`"
                    transform="rotate(-90 50 50)"
                    style="transition:stroke-dasharray .5s var(--ease)"/>
          </svg>
          <div class="an-pct">{{ busyPct || task.progress }}<span>%</span></div>
        </div>
        <div class="an-stage" role="status">{{ busyStage || task.stage || '分析中' }}</div>
        <p class="an-file truncate" :title="task.file?.filename">{{ task.file?.filename || task.name }}</p>
        <div class="an-steps">
          <div v-for="(s, i) in ANALYSIS_STEPS" :key="i" class="an-step"
               :class="{ done: (busyPct || task.progress) > s.pct,
                         now: (busyPct || task.progress) > (ANALYSIS_STEPS[i-1]?.pct ?? -1) &&
                              (busyPct || task.progress) <= s.pct }">
            <span class="as-dot"></span>
            <span class="as-txt">{{ s.label }}</span>
          </div>
        </div>
        <div v-if="err" class="err-box mt-14" role="alert">{{ err }}</div>
        <button v-if="task.status === 'analyzing'" class="btn mt-14"
                :disabled="cancelling" @click="cancelAnalysis">取消分析</button>
      </div>
    </div>

    <!-- ==================== 分析失败 ==================== -->
    <div v-else-if="task.status === 'failed'" class="fail-wrap">
      <div class="err-box">
        <strong>分析失败</strong>
        <div class="mt-10">{{ task.error_message || '未知错误' }}</div>
      </div>
      <button class="btn mt-14" @click="reset">重新上传</button>
    </div>

    <!-- ==================== 已取消 ==================== -->
    <div v-else-if="task.status === 'cancelled'" class="fail-wrap">
      <div class="info-box">
        <strong>分析已取消</strong>
        <div class="mt-10">已保留上传文件，可重新分析；如不需要，可新建分析。</div>
      </div>
      <button class="btn mt-14" :disabled="reanalyzing" @click="reanalyze">重新分析</button>
      <button class="btn mt-14" style="margin-left:8px" @click="reset">新建分析</button>
      <div v-if="err" class="err-box mt-14" role="alert">{{ err }}</div>
    </div>

    <div v-else-if="!overview" class="fail-wrap">
      <p v-if="loadingResults" role="status">正在读取分析结果…</p>
      <template v-else>
        <p class="err-box" role="alert">{{ err || '无法读取分析结果。' }}</p>
        <button class="btn mt-14" @click="loadAll">重试</button>
        <button class="btn mt-14" @click="reset">新建分析</button>
      </template>
    </div>

    <!-- ==================== 结果瀑布 ==================== -->
    <template v-else-if="task.status === 'completed'">
      <PrecisionWorkspace :key="task.id" :task="task" :overview="overview" :sessions="sessions"
        :streams="streams" :events="diagnostics" :metrics="metrics" :metrics-error="metricsError" :metrics-pending="metricsPending"
        :packets="packets" :packet-total="packetTotal" :expanded="expandedReport"
        @expand="toggleReport" />
      <template v-if="expandedReport">
      <!-- 进度导航 -->
      <nav class="spy glass-panel">
        <div class="spy-in">
          <button v-for="s in spyList" :key="s.k" class="spy-btn"
            :class="{ on: activeSection === s.k }"
            @click="scrollTo(s.k)">{{ s.l }}</button>
          <span class="spacer"></span>
          <span class="spy-file mono-sm truncate">
            {{ task.file?.filename }}
          </span>
          <details class="exp">
            <summary class="btn-mini">导出报告</summary>
            <div class="exp-menu">
              <a :href="reportUrl('md')" download>Markdown（.md）</a>
              <a :href="reportUrl('html')" download>离线 HTML</a><a :href="reportUrl('csv')" download>诊断 CSV</a>
              <a :href="reportUrl('json')" download>JSON（.json）</a>
            </div>
          </details>
          <a class="btn-mini exp-alt" :href="reportUrl('md')" download
             aria-label="导出 Markdown 报告">导出 .md</a>
          <a class="btn-mini exp-alt" :href="reportUrl('json')" download
             aria-label="导出 JSON 报告">导出 .json</a>
          <button class="btn-mini" @click="reset">新建分析</button>
        </div>
      </nav>

      <CaptureFlow v-if="overview && !loadingResults" :stages="flowStages" :filename="task.file?.filename || task.name"
                   :has-sessions="sessions.length > 0" @navigate="scrollTo" />
      <CaptureEvidence v-if="overview && !loadingResults" :key="task.id" :task-id="task.id" :streams="streams" />
      <section v-if="priorityFindings.length" class="sec mb-20 findings" aria-labelledby="findings-title">
        <div class="sec-head">
          <h2 id="findings-title" class="sec-title">优先排查</h2>
          <span class="spacer"></span>
          <router-link to="/diagnostics" class="btn-mini">全部诊断 <AppIcon name="forward" /></router-link>
        </div>
        <ul>
          <li v-for="d in priorityFindings" :key="d.id">
            <span class="badge" :class="SEV_CLS[d.severity]">{{ d.severity === 'critical' ? '严重' : '警告' }}</span>
            <div>
              <strong>{{ d.title }}</strong>
              <p>{{ d.description }}</p>
            </div>
            <span class="badge" :class="EV_CLS[d.evidence_level]">{{ EV[d.evidence_level] }}</span>
            <div v-if="d.related_packet_ids?.length" class="evidence-links">
              <router-link v-for="packet in d.related_packet_ids.slice(0, 2)" :key="packet"
                           :to="{ name: 'packets', query: { number: packet } }">报文 #{{ packet }} <AppIcon name="forward" /></router-link>
            </div>
            <router-link v-else-if="d.session_id" :to="`/sessions/${d.session_id}`">查看会话 <AppIcon name="forward" /></router-link>
          </li>
        </ul>
      </section>
      <section v-else-if="!loadingResults && !err" class="sec mb-20 findings" aria-labelledby="findings-empty-title">
        <div class="sec-head">
          <h2 id="findings-empty-title" class="sec-title">优先排查</h2>
          <span class="spacer"></span>
          <router-link to="/diagnostics" class="btn-mini">全部诊断 <AppIcon name="forward" /></router-link>
        </div>
        <p class="findings-empty">当前规则未发现严重或警告事件。结论仅覆盖已实现的规则和本次抓包范围，不能据此确认端到端正常。</p>
      </section>

      <!-- ===== 1. 总览 ===== -->
      <section id="sec-kpi" class="sec rise mb-20">
        <div class="sec-head">
          <span class="sec-num">{{ secNums.kpi }}</span>
          <span class="sec-title">分析总览</span>
          <span class="sec-sub">
            {{ task.file?.packet_count?.toLocaleString() }} 报文 ·
            {{ task.file?.duration?.toFixed(1) }}s ·
            {{ task.file?.link_type }}
          </span>
          <span class="spacer"></span>
          <span v-if="summary.capture_warnings" class="badge warning">
            {{ summary.capture_warnings }} 项抓包提示
          </span>
        </div>
        <div class="sec-body">
          <!-- 无信令时：用媒体视角展示（纯 RTP 码流包） -->
          <div v-if="!hasSignal && mediaStats" class="kpis mb-20">
            <div class="kpi">
              <div class="kpi-label">报文总数</div>
              <div class="kpi-value">{{ (summary.packet_count || 0).toLocaleString() }}</div>
              <div class="kpi-sub">{{ task.file?.duration?.toFixed(1) }}s 抓包时长</div>
            </div>
            <div class="kpi ok">
              <div class="kpi-label">RTP 流</div>
              <div class="kpi-value ok">{{ mediaStats.total }}</div>
              <div class="kpi-sub">{{ mediaStats.total_packets.toLocaleString() }} 个包</div>
            </div>
            <div class="kpi" :class="mediaStats.rebuilt ? 'ok' : 'warning'">
              <div class="kpi-label">成功解码</div>
              <div class="kpi-value" :class="mediaStats.rebuilt ? 'ok' : 'warning'">
                {{ mediaStats.rebuilt }}
                <span class="kpi-unit">/ {{ mediaStats.total }}</span>
              </div>
              <div class="kpi-sub">可播放视频</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">合计码率</div>
              <div class="kpi-value">
                {{ (mediaStats.total_bitrate / 1000).toFixed(1) }}
                <span class="kpi-unit">Mbps</span>
              </div>
              <div class="kpi-sub">所有流总和</div>
            </div>
            <div class="kpi" :class="mediaStats.avg_jitter > 50 ? 'warning' : 'ok'">
              <div class="kpi-label">平均抖动</div>
              <div class="kpi-value" :class="mediaStats.avg_jitter == null ? 'na'
                : (mediaStats.avg_jitter > 50 ? 'warning' : 'ok')">
                {{ mediaStats.avg_jitter != null ? mediaStats.avg_jitter : '—' }}
                <span v-if="mediaStats.avg_jitter != null" class="kpi-unit">ms</span>
              </div>
              <div class="kpi-sub">RFC 3550</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">编码 / 分辨率</div>
              <div class="kpi-value sm" style="font-size:15px">
                {{ Object.keys(mediaStats.codecs).join('/') || '—' }}
              </div>
              <div class="kpi-sub">
                {{ Object.entries(mediaStats.resolutions).map(([k,v]) => k + '×' + v).join(' · ') || '—' }}
              </div>
            </div>
            <div class="kpi">
              <div class="kpi-label">信令</div>
              <div class="kpi-value na" style="font-size:15px">未捕获</div>
              <div class="kpi-sub">该抓包不含 SIP</div>
            </div>
          </div>

          <!-- 提示：无信令 -->
          <div v-if="!hasSignal" class="info-box mb-20">
            <strong>这个抓包不含 SIP 信令</strong> —— 只能做媒体层分析。
            媒体流无法归属到具体设备或点播会话（没有 INVITE 上下文）。
            要还原完整点播链路，需要在信令与媒体都经过的节点重新抓包。
          </div>

          <div v-if="hasSignal" class="kpis">
            <div class="kpi">
              <div class="kpi-label">报文总数</div>
              <div class="kpi-value">{{ (summary.packet_count || 0).toLocaleString() }}</div>
              <div class="kpi-sub">{{ task.file?.duration?.toFixed(2) }}s 抓包时长</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">点播会话</div>
              <div class="kpi-value">{{ summary.session_count ?? 0 }}</div>
              <div class="kpi-sub">SIP 业务会话</div>
            </div>
            <div class="kpi" :class="summary.signal_success_rate >= 90 ? 'ok' : 'warning'">
              <div class="kpi-label">信令建立成功率</div>
              <div class="kpi-value" :class="summary.signal_success_rate == null ? 'na'
                : (summary.signal_success_rate >= 90 ? 'ok' : 'warning')">
                {{ summary.signal_success_rate != null ? fmt(summary.signal_success_rate, 1) : '—' }}
                <span v-if="summary.signal_success_rate != null" class="kpi-unit">%</span>
              </div>
              <div class="kpi-sub">{{ summary.signal_success || 0 }}/{{ summary.session_count || 0 }} 成功</div>
            </div>
            <div class="kpi" :class="summary.sessions_with_media ? 'ok' : 'critical'">
              <div class="kpi-label">发现媒体</div>
              <div class="kpi-value" :class="summary.sessions_with_media ? 'ok' : 'critical'">
                {{ summary.sessions_with_media ?? 0 }}
                <span class="kpi-unit">/ {{ summary.session_count || 0 }}</span>
              </div>
              <div class="kpi-sub">{{ summary.total_streams || 0 }} 条 RTP 流</div>
            </div>
            <div class="kpi" :class="diagTone">
              <div class="kpi-label">异常事件</div>
              <div class="kpi-value" :class="diagTone">{{ diagTotal }}</div>
              <div class="kpi-sub">
                {{ summary.diagnostics?.critical || 0 }} 严重 ·
                {{ summary.diagnostics?.warning || 0 }} 警告
              </div>
            </div>
            <div class="kpi">
              <div class="kpi-label">首媒体包耗时</div>
              <div class="kpi-value sm" :class="latencyTone">
                {{ summary.avg_first_media_latency != null
                    ? fmt(summary.avg_first_media_latency, 3) : '无法计算' }}
                <span v-if="summary.avg_first_media_latency != null" class="kpi-unit">s</span>
              </div>
              <div class="kpi-sub">INVITE → 首个 RTP</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">RTP 抖动</div>
              <div class="kpi-value sm" :class="summary.avg_jitter_ms == null ? 'na'
                : (summary.avg_jitter_ms > 50 ? 'warning' : 'ok')">
                {{ summary.avg_jitter_ms != null ? fmt(summary.avg_jitter_ms, 2) : '无媒体' }}
                <span v-if="summary.avg_jitter_ms != null" class="kpi-unit">ms</span>
              </div>
              <div class="kpi-sub">RFC 3550 平均值</div>
            </div>
          </div>

          <div class="g3 mt-20">
            <div class="mini-card">
              <div class="mc-head">业务分布</div>
              <div class="mc-chart" id="c-biz"></div>
            </div>
            <div class="mini-card">
              <div class="mc-head">SIP 响应码</div>
              <div class="mc-chart" id="c-code"></div>
            </div>
            <div class="mini-card">
              <div class="mc-head">会话状态</div>
              <div v-if="summary.session_count" class="mc-chart" id="c-state"></div>
              <div v-else class="mc-summary">
                <div class="ms-row">
                  <span>信令成功</span>
                  <b class="ok">{{ overview?.signal_distribution?.success || 0 }}</b>
                </div>
                <div class="ms-row">
                  <span>信令失败</span>
                  <b :class="overview?.signal_distribution?.failed ? 'crit' : ''">
                    {{ overview?.signal_distribution?.failed || 0 }}
                  </b>
                </div>
                <div class="ms-row">
                  <span>无媒体</span>
                  <b :class="overview?.media_distribution?.no_media ? 'crit' : ''">
                    {{ overview?.media_distribution?.no_media || 0 }}
                  </b>
                </div>
                <div class="ms-foot">
                  暂无点播会话
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ===== 信令 ===== -->
      <section v-if="hasSignal" id="sec-signal" class="sec rise mb-20">
        <div class="sec-head clickable" @click="toggle('signal')">
          <span class="sec-num">{{ secNums.signal }}</span>
          <span class="sec-title">SIP 信令分析</span>
          <span class="sec-sub">{{ summary.session_count ?? sessions.length }} 个会话</span>
          <span class="spacer"></span>
          <router-link to="/sip" class="btn-mini" @click.stop>信令时序图 <AppIcon name="forward" /></router-link>
          <span class="chev" :class="{ open: openSections.signal }"><AppIcon name="next" /></span>
        </div>
        <Transition name="panel-slide">
        <div v-show="openSections.signal" class="sec-body flush">
          <table class="tbl clickable" v-if="sessions.length">
            <thead>
              <tr>
                <th>会话</th><th>设备 / 通道 ID</th><th>开始</th><th>时长</th>
                <th>信令</th><th>媒体</th><th>结束</th><th>诊断</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in sessions" :key="s.id" tabindex="0" @click="goSession(s.id)" @keydown.enter="goSession(s.id)">
                <td class="mono">#{{ s.id }}</td>
                <td class="mono truncate" style="max-width:220px">{{ s.device_id || '—' }}</td>
                <td class="mono-sm">{{ s.start_time?.toFixed(2) }}s</td>
                <td class="num">{{ s.total_duration != null ? s.total_duration.toFixed(2) + 's' : '—' }}</td>
                <td>
                  <span class="badge" :class="s.signal_status === 'success' ? 'ok'
                    : (s.signal_status === 'failed' ? 'critical' : 'warning')">
                    {{ { success:'成功', failed:'失败', incomplete:'不完整', unknown:'未知' }[s.signal_status] }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="s.media_status === 'received' ? 'ok'
                    : (s.media_status === 'no_media' ? 'critical' : 'warning')">
                    {{ { received:'已收到', no_media:'无媒体', undecodable:'不可解码', unknown:'未知' }[s.media_status] }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="s.end_reason === 'normal' ? 'ok' : 'warning'">
                    {{ { normal:'正常', abnormal:'异常', capture_ended:'抓包结束', unknown:'未知' }[s.end_reason] }}
                  </span>
                </td>
                <td>
                  <span v-if="s.critical_count" class="badge critical">{{ s.critical_count }}</span>
                  <span v-else-if="s.warning_count" class="badge warning">{{ s.warning_count }}</span>
                  <span v-else class="badge ok">—</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">
            未识别到点播会话
            <div class="hint">抓包中可能不含 INVITE 信令，或抓包点位于信令路径之外</div>
          </div>
        </div>
        </Transition>
      </section>

      <!-- ===== 3. 媒体 ===== -->
      <section v-if="hasMedia" id="sec-media" class="sec rise mb-20">
        <div class="sec-head clickable" @click="toggle('media')">
          <span class="sec-num">{{ secNums.media }}</span>
          <span class="sec-title">RTP 媒体质量</span>
          <span class="sec-sub">{{ streams.length }} 条流</span>
          <span class="spacer"></span>
          <span v-if="!streams.length" class="badge critical">未捕获媒体</span>
          <router-link to="/media" class="btn-mini" @click.stop>详细分析 <AppIcon name="forward" /></router-link>
          <span class="chev" :class="{ open: openSections.media }"><AppIcon name="next" /></span>
        </div>
        <Transition name="panel-slide">
        <div v-show="openSections.media" class="sec-body">
          <template v-if="streams.length">
            <p v-if="metricsError" class="hint">媒体趋势暂时无法读取。</p>
            <p v-else-if="streams.length > TREND_LIMIT" class="hint">
              趋势展示报文量最高的 {{ TREND_LIMIT }} 条流。
            </p>
            <div class="g2">
              <div class="mini-card">
                <div class="mc-head">媒体码率趋势</div>
                <div class="mc-chart lg" id="c-bitrate"></div>
              </div>
              <div class="mini-card">
                <div class="mc-head">RTP 抖动趋势</div>
                <div class="mc-chart lg" id="c-jitter"></div>
              </div>
            </div>

            <!-- 重建视频 -->
            <div v-if="playableStreams.length" id="sec-video" class="video-sec">
              <div class="vs-head">
                <span class="vs-title">视频画面还原</span>
                <span class="vs-sub">
                  {{ playableStreams.length }} 条流已生成预览
                  <template v-if="!hasSignal"> · 无信令，按 SSRC 编号</template>
                </span>
              </div>
              <div class="video-grid">
                <VideoPlayer v-for="st in visibleVideos"
                             :key="st.id" :stream="st" />
              </div>
              <div v-if="playableStreams.length > videoLimit"
                   class="video-more">
                <button class="btn sm" @click="showAllVideos = !showAllVideos">
                  {{ showAllVideos
                      ? '收起'
                      : `展开剩余 ${playableStreams.length - videoLimit} 条` }}
                </button>
              </div>
            </div>

            <div v-else id="sec-video" class="video-none">
              <div class="vn-icon">
                <AppIcon name="monitor" />
              </div>
              <div>
                <div class="vn-t">未能还原出视频画面</div>
                <div class="vn-s">请在「设置」检查 FFmpeg，或查看编码分析中的解析结果。</div>
              </div>
            </div>

            <div class="stream-grid mt-20">
              <div v-for="st in streams" :key="st.id" class="stream-card">
                <div class="sc-top">
                  <span class="mono sc-ssrc">0x{{ st.ssrc?.toString(16) }}</span>
                  <span class="proto">{{ st.transport }}</span>
                  <span v-if="st.extra?.link_mode === 'exact'"
                        class="badge success sc-link" title="SSRC 与 SDP 的 y= 精确匹配">
                    SSRC 匹配
                  </span>
                  <span v-else-if="st.extra?.link_mode === 'weak'"
                        class="badge warning sc-link"
                        title="仅按端口与时间窗关联，非 SSRC 精确匹配，归属存疑">
                    推断关联
                  </span>
                </div>
                <div class="sc-metrics">
                  <div><i>包数</i><b>{{ st.packet_count }}</b></div>
                  <div><i>码率</i><b>{{ st.avg_bitrate != null ? fmt(st.avg_bitrate, 0) : '—' }}<span>kbps</span></b></div>
                  <div><i>抖动</i><b :class="st.jitter_avg > 50 ? 'text-warning' : ''">
                    {{ st.jitter_avg != null ? fmt(st.jitter_avg, 2) : '—' }}<span>ms</span></b></div>
                  <div><i>缺口</i><b :class="st.seq_gap_packets ? 'text-critical' : ''">
                    {{ st.seq_gap_packets }}</b></div>
                </div>
                <div class="sc-bar">
                  <div class="sb-track">
                    <div class="sb-fill"
                         :style="{ transform: 'scaleX(' + Math.min(1, (st.avg_bitrate || 0) / 25000) + ')' }"></div>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="empty">
            未捕获到媒体流
            <div class="hint">
              可能是媒体未经过抓包点，或媒体端口未建立连接。<br/>
              信号成功不等于媒体成功，更不等于画面可播放。
            </div>
          </div>
        </div>
        </Transition>
      </section>

      <!-- ===== 4. 编码 ===== -->
      <section v-if="hasCodec" id="sec-codec" class="sec rise mb-20">
        <div class="sec-head clickable" @click="toggle('codec')">
          <span class="sec-num">{{ secNums.codec }}</span>
          <span class="sec-title">视频编码分析</span>
          <span class="sec-sub">
            PS / PES / ES 解封装
            <template v-if="codecSummary.codecs.length">
              · {{ codecSummary.codecs.join(' + ') }}
            </template>
          </span>
          <span class="spacer"></span>
          <span v-if="!codecList.length" class="text-na">无数据</span>
          <span class="chev" :class="{ open: openSections.codec }"><AppIcon name="next" /></span>
        </div>
        <Transition name="panel-slide">
        <div v-show="openSections.codec" class="sec-body">
          <template v-if="codecList.length">
            <div class="codec-kpis">
              <div class="ck">
                <i>编码格式</i>
                <b>{{ codecSummary.codecs.join(' / ') || '未识别' }}</b>
              </div>
              <div class="ck">
                <i>分辨率</i>
                <b>{{ codecSummary.resolution || '未解析' }}</b>
              </div>
              <div class="ck">
                <i>总帧数</i>
                <b>{{ codecSummary.totalFrames ?? '—' }}</b>
              </div>
              <div class="ck">
                <i>关键帧</i>
                <b>{{ codecSummary.totalKeyframes ?? '—' }}</b>
              </div>
            </div>

            <div class="codec-table mt-20">
              <table class="tbl">
                <thead>
                  <tr>
                    <th>SSRC</th><th>编码</th><th>Profile / Level</th>
                    <th>分辨率</th><th>帧数</th><th>关键帧</th>
                    <th>参数集</th><th>PS 包</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="x in codecList" :key="x.id">
                    <td class="mono">0x{{ x.ssrc?.toString(16) }}</td>
                    <td>
                      <span v-if="x.codec" class="badge brand">{{ x.codec }}</span>
                      <span v-else class="text-na">未识别</span>
                    </td>
                    <td class="mono-sm">
                      {{ x.ps?.video?.profile || '—' }}
                      <template v-if="x.ps?.video?.level"> / L{{ x.ps.video.level }}</template>
                      <template v-if="x.ps?.video?.bit_depth"> · {{ x.ps.video.bit_depth }} bit</template>
                    </td>
                    <td class="mono-sm">
                      {{ x.width && x.height ? `${x.width}×${x.height}` : '—' }}
                    </td>
                    <td class="num">{{ x.frameCount ?? '—' }}</td>
                    <td class="num" :class="x.keyframeCount ? 'text-ok' : ''">
                      {{ x.keyframeCount ?? '—' }}
                    </td>
                    <td>
                      <span v-if="x.ps?.video?.has_sps && x.ps?.video?.has_pps"
                            class="badge ok">SPS+PPS</span>
                      <span v-else-if="x.ps?.video?.has_sps" class="badge warning">仅 SPS</span>
                      <span v-else class="badge critical">缺失</span>
                    </td>
                    <td class="num">{{ x.ps?.pack_count ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="info-box mt-14">
              <strong>解析说明</strong>：分辨率与帧结构由 SPS 解析得出，不依赖 ffmpeg。
              若抓包起始于 GOP 中间，可能缺少参数集导致无法解析——
              此时显示「未识别」而非猜测值。
              <template v-if="codecList.some(x => x.psSampled)">
                编码结构只取样流开头 60 秒或 256 MiB，媒体质量指标仍覆盖完整流。
              </template>
            </div>
          </template>
          <div v-else class="empty">
            没有可解析的视频 ES 数据
            <div class="hint">
              可能原因：未捕获媒体流、载荷非 PS 封装、或抓包不完整
            </div>
          </div>
        </div>
        </Transition>
      </section>

      <!-- ===== 5. 诊断 ===== -->
      <section v-if="hasDiag" id="sec-diag" class="sec rise mb-20">
        <div class="sec-head clickable" @click="toggle('diag')">
          <span class="sec-num">{{ secNums.diag }}</span>
          <span class="sec-title">智能故障诊断</span>
          <span class="sec-sub">{{ diagTotal }} 条结论</span>
          <span class="spacer"></span>
          <span v-if="summary.diagnostics?.critical" class="badge critical">
            {{ summary.diagnostics.critical }} 严重
          </span>
          <router-link to="/diagnostics" class="btn-mini" @click.stop>全部 <AppIcon name="forward" /></router-link>
          <span class="chev" :class="{ open: openSections.diag }"><AppIcon name="next" /></span>
        </div>
        <Transition name="panel-slide">
        <div v-show="openSections.diag" class="sec-body">
          <div v-if="diagnostics.length" class="diag-list">
            <div v-for="d in diagnostics.slice(0, 8)" :key="d.id"
                 class="diag-item" :class="d.severity">
              <div class="di-head">
                <span class="badge" :class="SEV_CLS[d.severity]">{{ d.severity }}</span>
                <span class="di-rule mono">{{ d.rule_id }}</span>
                <span class="di-title">{{ d.title }}</span>
                <span class="spacer"></span>
                <span class="badge" :class="EV_CLS[d.evidence_level]">
                  {{ EV[d.evidence_level] }}
                </span>
              </div>
              <div class="di-desc">{{ d.description }}</div>
              <div class="di-foot">
                <span v-if="d.device_id" class="mono-sm">设备 {{ d.device_id }}</span>
                <span v-if="d.timestamp != null" class="mono-sm">{{ d.timestamp.toFixed(2) }}s</span>
                <span v-if="d.session_id" class="di-link" @click="goSession(d.session_id)">
                  会话 #{{ d.session_id }} →
                </span>
              </div>
            </div>
          </div>
          <div v-else class="empty">
            未发现异常
            <div class="hint">规则引擎未在该任务中检测到问题</div>
          </div>
        </div>
        </Transition>
      </section>

      <!-- ===== 6. 报文 ===== -->
      <section v-if="hasPacket" id="sec-packet" class="sec rise">
        <div class="sec-head clickable" @click="toggle('packet')">
          <span class="sec-num">{{ secNums.packet }}</span>
          <span class="sec-title">原始报文</span>
          <span class="sec-sub">{{ packetTotal.toLocaleString() }} 条</span>
          <span class="spacer"></span>
          <router-link to="/packets" class="btn-mini" @click.stop>查看全部 <AppIcon name="forward" /></router-link>
          <span class="chev" :class="{ open: openSections.packet }"><AppIcon name="next" /></span>
        </div>
        <Transition name="panel-slide">
        <div v-show="openSections.packet" class="sec-body flush">
          <table class="tbl clickable">
            <thead>
              <tr><th>#</th><th>时间</th><th>协议</th><th>源 → 目的</th><th>长度</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in packets" :key="p.id" tabindex="0" @click="goPacket(p.packet_number)" @keydown.enter="goPacket(p.packet_number)">
                <td class="mono">{{ p.packet_number }}</td>
                <td class="mono-sm">{{ p.timestamp?.toFixed(3) }}</td>
                <td><span class="proto">{{ p.protocol }}</span></td>
                <td class="mono-sm truncate" style="max-width:340px">
                  {{ p.source_ip }}:{{ p.source_port ?? '-' }} →
                  {{ p.destination_ip }}:{{ p.destination_port ?? '-' }}
                </td>
                <td class="num">{{ p.length }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!packets.length" class="empty">暂无报文</div>
        </div>
        </Transition>
      </section>

      <!-- ===== AI 分析概览 ===== -->
      <section id="sec-ai" class="rise mt-14 mb-20">
        <AiSummarySection :key="store.currentTaskId" />
      </section>

      <!-- 底部局限声明 -->
      <div class="foot-note">
        <strong>分析局限</strong>：所有结论仅反映抓包点观察到的流量，
        不代表端到端网络状况或客户端实际播放结果。
        SIP 成功 ≠ 媒体成功 ≠ 画面可播放。
        无法计算的指标显示为「无法计算」而非 0。
      </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.page.workstation {max-width:none;padding:10px 16px 24px}.workstation .task-breadcrumb{margin-bottom:6px}
#sec-video { scroll-margin-top:calc(var(--app-header-height) + 58px); }
.task-breadcrumb { display:flex; align-items:center; gap:10px; color:var(--text-3); font-size:12px; margin-bottom:32px; }
.task-breadcrumb strong { color:var(--text-2); }

/* ============ 分析中 ============ */
.analyzing-wrap {
  min-height: calc(100vh - var(--app-header-height));
  display: flex; align-items: center; justify-content: center;
  padding: 40px 20px;
}
.an-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 44px 56px;
  text-align: center;
  width: min(100%, 480px);
}
.an-ring { position: relative; width: 128px; height: 128px; margin: 0 auto 24px; }
.an-ring svg { width: 100%; height: 100%; }
.an-pct {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 30px; font-weight: 700;
  letter-spacing: -1px;
  color: var(--text);
}
.an-pct span { font-size: 15px; color: var(--text-3); margin-left: 1px; }
.an-stage {
  font-size: 15px; font-weight: 600;
  margin-bottom: 4px;
}
.an-file { color: var(--text-3); margin-bottom: 20px; }
.findings ul { list-style: none; }
.findings li {
  padding: 13px 18px; border-top: 1px solid var(--line);
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: baseline; gap: 12px;
}
.findings li:first-child { border-top: 0; }
.findings p, .findings a { font-size: 12px; }
.findings p { color: var(--text-2); }
.findings-empty { padding: 16px 18px; line-height: 1.6; }
.findings li a { white-space: nowrap; }
.evidence-links { display: flex; flex-wrap: wrap; gap: 4px 10px; }
@media (max-width: 600px) {
  .an-card { padding: 26px 18px; }
  .findings li { grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
}
.an-steps {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 8px 22px; text-align: left;
}
.an-step {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-4);
  transition: color var(--dur) var(--ease);
  padding: 3px 0;
}
.an-step .as-txt { transition: all var(--dur) var(--ease); }
.an-step.done .as-txt { opacity: .8; }
.an-step.now .as-txt {
  font-weight: 600;
  transform: translateX(2px);
}
.as-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--line-strong); flex: none;
  transition: all .3s;
}
.an-step.done { color: var(--text-2); }
.an-step.done .as-dot { background: var(--ok); }
.an-step.now { color: var(--text); font-weight: 600; }
.an-step.now .as-dot {
  background: var(--info);
  box-shadow: 0 0 0 3px var(--info-soft);
  animation: pulse 1.4s ease-in-out infinite;
}

.fail-wrap { max-width: 600px; margin: 60px auto; }

/* ============ 滚动导航 ============ */
.spy {
  position: sticky; top: var(--app-header-height); z-index: 50;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
  margin: -26px -28px 22px;
  padding: 0 28px;
}
.page :is(section[id^="sec-"]) { scroll-margin-top: calc(var(--app-header-height) + 58px); }
.spy-in {
  min-width: 0; margin: 0 auto;
  height: 48px; display: flex; align-items: center; gap: 4px;
}
.spy-btn {
  padding: 6px 14px;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  color: var(--text-3);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  position: relative;
}
.spy-btn:hover { color: var(--text); background: var(--surface); }
.spy-btn.on { color: var(--brand-lt); font-weight: 650; }
.spy-btn.on::after {
  content: ''; position: absolute;
  left: 14px; right: 14px; bottom: -1px; height: 2px;
  background: var(--brand);
}
.spy-file { color: var(--text-4); max-width: 280px; margin-right: 10px; }
@media (max-width: 1080px) {
  .spy { margin: -20px -16px 18px; padding: 0 16px; }
}
@media (max-width: 720px) {
  .spy { overflow-x: auto; scrollbar-width: none; }
  .spy::-webkit-scrollbar { display: none; }
  .spy-in { height: 42px; gap: 0; min-width: max-content; }
  .spy-btn { height: 42px; padding: 0 11px; white-space: nowrap; font-size: 12px; }
  .spy-btn.on::after { left: 11px; right: 11px; bottom: 0; }
  .spy-file { display: none; }
}

/* 导出：挂在导航右侧，不额外占一栏；两种格式写清后缀，避免下错文件 */
.exp { position: relative; }
.exp > summary { list-style: none; cursor: pointer; user-select: none; }
.exp > summary::-webkit-details-marker { display: none; }
.exp[open] > summary {
  background: var(--surface-3); border-color: var(--line-strong); color: var(--text);
}
.exp-menu {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 60;
  min-width: 168px; padding: 4px;
  background: var(--surface);
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
}
.exp-menu a {
  display: block; padding: 7px 10px;
  border-radius: var(--radius-xs);
  color: var(--text-2); font-size: 12.5px; text-decoration: none;
}
.exp-menu a:hover { background: var(--surface-3); color: var(--text); }

.exp-alt { display: none; }
/* 移动端导航横向滚动，绝对定位菜单会被 overflow 裁掉：
   收起下拉，改为两个平铺链接 */
@media (max-width: 720px) {
  .exp { display: none; }
  .exp-alt { display: inline-flex; }
}

/* ============ 区块 ============ */
/* 单次错峰进场：同一屏的区块依次出现，不做逐卡 hover 位移 */
section.rise:nth-of-type(2) { animation-delay: .05s; }
section.rise:nth-of-type(3) { animation-delay: .10s; }
section.rise:nth-of-type(4) { animation-delay: .15s; }
section.rise:nth-of-type(5) { animation-delay: .20s; }
section.rise:nth-of-type(6) { animation-delay: .25s; }
section.rise:nth-of-type(7) { animation-delay: .30s; }

.clickable { cursor: pointer; user-select: none; }
.clickable:hover { background: var(--surface-3); }
.chev {
  color: var(--text-4); font-size: 16px;
  transition: transform var(--dur) var(--ease);
  margin-left: 4px;
}
.chev.open { transform: rotate(90deg); }

/* 图表是报告的"栏"，不是再套一层卡片 */
.mini-card {
  border-top: 1px solid var(--line-2);
  min-width: 0;
}
.mc-head {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 0 8px;
  font-size: 12px; font-weight: 550;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
}
.mc-chart { height: 180px; margin-top: 6px; }
.mc-chart.lg { height: 218px; }
.mc-summary { padding: 12px 0 4px; }
.ms-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px; color: var(--text-3);
}
.ms-row b {
  font-family: var(--font-mono);
  font-size: 15px; font-weight: 600;
  color: var(--text);
}
.ms-row b.ok { color: var(--ok); }
.ms-row b.crit { color: var(--critical); }
.ms-foot {
  margin-top: 10px;
  font-size: 11px; color: var(--text-4); line-height: 1.55;
}


/* 视频区 */
.video-sec { margin-bottom: 20px; }
.vs-head {
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 12px;
}
.vs-title { font-size: 13px; font-weight: 600; color: var(--text); }
.vs-sub { font-size: 11px; color: var(--text-4); }
.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}

.video-more {
  display: flex; justify-content: center;
  margin-top: 14px;
}

.video-none {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px;
  background: var(--surface-2);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
}
.vn-icon {
  width: 40px; height: 40px; flex: none;
  border-radius: 11px;
  background: var(--surface-3);
  border: 1px solid var(--line-2);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-4);
}
.vn-icon svg { width: 18px; height: 18px; }
.vn-t { font-size: 12.5px; color: var(--text-2); font-weight: 550; margin-bottom: 4px; }
.vn-s { font-size: 11.5px; color: var(--text-4); line-height: 1.7; }

/* 媒体流卡 */
.stream-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.stream-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  transition: border-color var(--dur) var(--ease);
}
.stream-card:hover { border-color: var(--line-strong); }
.sc-top {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 12px;
}
.sc-ssrc { font-size: 12px; color: var(--brand-lt); font-weight: 600; }
.sc-link { font-size: 10px; padding: 1px 6px; margin-left: auto; cursor: help; }
.sc-metrics {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.sc-metrics > div { display: flex; flex-direction: column; gap: 2px; }
.sc-metrics i { font-size: 10px; color: var(--text-4); font-style: normal; }
.sc-metrics b {
  font-size: 14px; font-weight: 650;
  color: var(--text); font-variant-numeric: tabular-nums;
}
.sc-metrics b span { font-size: 9.5px; color: var(--text-4); font-weight: 400; margin-left: 1px; }
.sc-bar { margin-top: 12px; }
.sb-track {
  height: 3px; background: var(--surface-4);
  border-radius: 99px; overflow: hidden;
}
.sb-fill {
  height: 100%;
  background: var(--info);
  border-radius: 99px;
  transform-origin: left center;
  transition: transform .35s var(--ease);
}

/* 编码 */
.codec-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}
.ck {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 13px 16px;
}
.ck i {
  display: block; font-size: 10.5px;
  color: var(--text-4); font-style: normal; margin-bottom: 5px;
}
.ck b {
  font-size: 16px; font-weight: 650;
  color: var(--text); letter-spacing: -.3px;
}
.codec-table {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

/* 诊断 */
.diag-list { display: flex; flex-direction: column; gap: 10px; }
.diag-item {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 13px 16px;
  transition: border-color var(--dur) var(--ease);
}
.diag-item:hover { border-color: var(--line-strong); }

.di-head {
  display: flex; align-items: center; gap: 9px;
  flex-wrap: wrap; margin-bottom: 6px;
}
.di-rule { font-size: 11px; color: var(--text-4); }
.di-title { font-size: 13px; font-weight: 600; color: var(--text); }
.di-desc {
  font-size: 12.5px; color: var(--text-2);
  line-height: 1.72;
}
.di-foot {
  display: flex; gap: 16px; flex-wrap: wrap;
  margin-top: 8px; align-items: center;
}
.di-link {
  font-size: 11.5px; color: var(--brand-lt);
  cursor: pointer; font-weight: 500;
}
.di-link:hover { text-decoration: underline; }

/* 底部 */
.foot-note {
  margin-top: 26px; padding: 18px 22px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  font-size: 12px; color: var(--text-3);
  line-height: 1.8;
}
.foot-note strong { color: var(--text-2); }
</style>
