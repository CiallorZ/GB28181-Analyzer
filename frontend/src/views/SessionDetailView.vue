<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadECharts } from '../utils/chartLoader'
import { chartBase as baseOption, chartPalette } from '../utils/chartTheme'
import { bindChartResize } from '../utils/chartResize'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'

const route = useRoute()
const router = useRouter()
const sid = Number(route.params.id)

const session = ref(null)
const sip = ref([])
const timeline = ref([])
const showAllEvents = ref(false)
const visibleTimeline = computed(() => showAllEvents.value ? timeline.value : timeline.value.slice(0, 30))
const streams = ref([])
const metrics = ref([])
const diagnostics = ref([])
const loading = ref(true)
const err = ref('')
const selectedMsg = ref(null)
const filterMethod = ref('')
const filterCallId = ref('')

const charts = {}
async function chart(id, opt) {
  const el = document.getElementById(id)
  if (!el) return
  // 图表库是异步加载的，等它回来时容器可能已经因切换任务被移除
  const echarts = await loadECharts()
  if (!el.isConnected) return
  if (!charts[id]) charts[id] = echarts.init(el)
  charts[id].setOption(opt, true)
}

const chartBase = (extra = {}) => baseOption({
  grid: { left: 52, right: 16, top: 20, bottom: 26 },
  tooltip: { trigger: 'axis' },
  ...extra
})

let C = chartPalette()

async function load() {
  loading.value = true
  try {
    session.value = await api.session(sid)
    const [sipRes, tlRes, mediaRes, metricRes, diagRes] = await Promise.all([
      api.sessionSip(sid), api.sessionTimeline(sid),
      api.sessionMedia(sid), api.sessionMetrics(sid),
      api.sessionDiagnostics(sid)
    ])
    sip.value = sipRes.items || []
    timeline.value = tlRes.items || []
    streams.value = mediaRes.items || []
    metrics.value = metricRes.items || []
    diagnostics.value = diagRes.items || []
    await nextTick()
    renderCharts()
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

function renderCharts() {
  C = chartPalette()
  // 码率趋势
  const brSeries = []
  metrics.value.forEach((m, i) => {
    if (!m.bitrate_series?.length) return
    brSeries.push({
      name: 'SSRC ' + (m.ssrc || i),
      type: 'line', smooth: true, showSymbol: false,
      lineStyle: { width: 1.6 },
      data: m.bitrate_series.map(p => [p.t, p.v])
    })
  })
  chart('chart-bitrate', chartBase({
    legend: { top: 0, textStyle: { color: C.dim, fontSize: 11 } },
    xAxis: { type: 'value', name: '秒', axisLine: { lineStyle: { color: C.line2 } },
             splitLine: { lineStyle: { color: C.line } } },
    yAxis: { type: 'value', name: 'kbps', splitLine: { lineStyle: { color: C.line } } },
    series: brSeries.length ? brSeries : []
  }))

  // 抖动趋势
  const jSeries = []
  metrics.value.forEach((m, i) => {
    if (!m.jitter_series?.length) return
    jSeries.push({
      name: 'SSRC ' + (m.ssrc || i),
      type: 'line', smooth: true, showSymbol: false,
      lineStyle: { width: 1.6 },
      data: m.jitter_series.map(p => [p.t, p.v])
    })
  })
  chart('chart-jitter', chartBase({
    legend: { top: 0, textStyle: { color: C.dim, fontSize: 11 } },
    xAxis: { type: 'value', name: '秒', axisLine: { lineStyle: { color: C.line2 } },
             splitLine: { lineStyle: { color: C.line } } },
    yAxis: { type: 'value', name: 'ms', splitLine: { lineStyle: { color: C.line } } },
    series: jSeries.length ? jSeries : []
  }))
}

const SIG_ROLES = computed(() => {
  // 从 SIP 消息里抽取参与方（按出现顺序）
  const seen = []
  sip.value.forEach(m => {
    if (m.source_ip && !seen.includes(m.source_ip)) seen.push(m.source_ip)
    if (m.destination_ip && !seen.includes(m.destination_ip)) seen.push(m.destination_ip)
  })
  return seen.slice(0, 4)
})

const filteredSip = computed(() => {
  let arr = sip.value
  if (filterMethod.value) {
    arr = arr.filter(m => (m.method || String(m.status_code)) === filterMethod.value)
  }
  if (filterCallId.value) {
    arr = arr.filter(m => (m.call_id || '').includes(filterCallId.value))
  }
  return arr
})

const methods = computed(() => {
  const s = new Set()
  sip.value.forEach(m => s.add(m.method || String(m.status_code)))
  return [...s].sort()
})

// 时序图布局
const TIMELINE_H = computed(() => Math.max(200, filteredSip.value.length * 26 + 70))

function laneX(ip) {
  const roles = SIG_ROLES.value
  const n = roles.length || 1
  if (n === 1) return 500
  const idx = Math.max(0, roles.indexOf(ip))
  const pad = 130
  return pad + idx * ((1000 - pad * 2) / (n - 1))
}

function selectMsg(m) {
  selectedMsg.value = m
}

function gotoPacket(packetId) {
  if (!packetId) return
  router.push({ name: 'packets', query: { task: session.value?.task_id, number: packetId } })
}

function downloadSvg() {
  const svg = document.getElementById('sip-timeline')
  if (!svg) return
  const data = new XMLSerializer().serializeToString(svg)
  const blob = new Blob([data], { type: 'image/svg+xml' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `session-${sid}-timeline.svg`
  a.click()
}

const fmt = (v, d = 3) => v == null ? '—' : Number(v).toFixed(d)

let unbindResize = null
onMounted(async () => {
  await load()
  unbindResize = bindChartResize(charts)
})
onUnmounted(() => unbindResize?.())
</script>

<template>
  <div class="page">
    <PageNav
      :title="`会话 #${sid}`"
      :sub="session ? `${session.device_id || '未知设备'} · ${session.session_type === 'live' ? '实时点播' : '回放'} · ${session.start_time?.toFixed(2)}s 开始` : ''"
      :crumbs="[{label:'工作台', to:'/'}, {label:'点播会话', to:'/sessions'}, {label:`会话 #${sid}`}]" />

    <div v-if="err" class="err-box">{{ err }}</div>

    <template v-if="session">
      <!-- 会话摘要 -->
      <div class="kpis k8 mb-16">
        <div class="kpi">
          <div class="kpi-label">设备 ID</div>
          <div class="kpi-mono">{{ session.device_id || '—' }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">信令状态</div>
          <div class="kpi-value" :class="session.signal_status === 'success' ? 'ok' : 'critical'">
            {{ { success: '成功', failed: '失败', incomplete: '不完整', unknown: '未知' }[session.signal_status] }}
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">媒体状态</div>
          <div class="kpi-value" :class="session.media_status === 'received' ? 'ok' : 'critical'">
            {{ { received: '已收到', no_media: '无媒体', undecodable: '不可解码', unknown: '未知' }[session.media_status] }}
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">会话时长</div>
          <div class="kpi-value">{{ fmt(session.total_duration, 2) }}<span class="kpi-unit">s</span></div>
        </div>
        <div class="kpi">
          <div class="kpi-label">INVITE 响应</div>
          <div class="kpi-value" :class="session.invite_latency == null ? 'na' : ''">
            {{ session.invite_latency != null ? fmt(session.invite_latency, 3) : '无法计算' }}
            <span v-if="session.invite_latency != null" class="kpi-unit">s</span>
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">首媒体包</div>
          <div class="kpi-value" :class="session.first_media_latency == null ? 'na' : 'warning'">
            {{ session.first_media_latency != null ? fmt(session.first_media_latency, 3) : '无媒体' }}
            <span v-if="session.first_media_latency != null" class="kpi-unit">s</span>
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">结束原因</div>
          <div class="kpi-value" style="font-size:14px" :class="session.end_reason === 'normal' ? 'ok' : 'warning'">
            {{ { normal: '正常', abnormal: '异常', capture_ended: '抓包结束', unknown: '未知' }[session.end_reason] }}
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">诊断</div>
          <div class="kpi-value" :class="session.critical_count ? 'critical' : (session.warning_count ? 'warning' : 'ok')">
            {{ session.diagnostic_count }}
          </div>
        </div>
      </div>

      <!-- 协商参数 -->
      <div class="card mb-16">
        <div class="card-head">SDP 协商参数</div>
        <div class="card-body">
          <div class="param-grid">
            <div class="param">
              <span>协商地址</span>
              <b class="mono">{{ session.negotiated_ip || '—' }}</b>
            </div>
            <div class="param">
              <span>协商端口</span>
              <b class="mono">{{ session.negotiated_port || '—' }}</b>
            </div>
            <div class="param">
              <span>传输方式</span>
              <b>{{ session.negotiated_transport || '—' }}</b>
            </div>
            <div class="param">
              <span>Subject SSRC</span>
              <b class="mono">{{ session.subject_ssrc || '—' }}</b>
            </div>
            <div class="param">
              <span>SDP y= SSRC</span>
              <b class="mono">{{ session.sdp_ssrc || '—' }}</b>
            </div>
            <div class="param">
              <span>媒体流数</span>
              <b>{{ session.media_stream_count }}</b>
            </div>
          </div>
          <div v-if="session.subject_ssrc && session.sdp_ssrc && session.subject_ssrc.replace(/^0+/,'') !== session.sdp_ssrc.replace(/^0+/,'')"
               class="ssrc-warn">
            ⚠ SSRC 不一致：Subject 为 {{ session.subject_ssrc }}，SDP y= 为 {{ session.sdp_ssrc }}
          </div>
        </div>
      </div>

      <section class="card mb-16" aria-labelledby="event-timeline-title">
        <div class="card-head">
          <span id="event-timeline-title">信令与媒体事件</span>
          <span class="count-badge">{{ timeline.length }} 条</span>
          <span class="spacer"></span>
          <button v-if="timeline.length > 30" class="btn-mini" @click="showAllEvents = !showAllEvents">
            {{ showAllEvents ? '收起' : '查看全部' }}
          </button>
        </div>
        <ol v-if="visibleTimeline.length" class="event-timeline">
          <li v-for="(event, index) in visibleTimeline" :key="`${event.type}-${event.timestamp}-${index}`">
            <time class="event-time mono">{{ fmt(event.timestamp, 3) }}s</time>
            <span class="event-dot" :class="event.severity"></span>
            <div class="event-content">
              <strong>{{ event.label }}</strong>
              <p>{{ event.detail }}</p>
            </div>
            <button v-if="event.packet_id || event.related_packet_ids?.length" class="btn-mini"
                    @click="gotoPacket(event.packet_id || event.related_packet_ids[0])">查看报文</button>
          </li>
        </ol>
        <div v-else class="empty">没有可定位时间的事件</div>
      </section>

      <!-- SIP 时序图 -->
      <div class="card mb-16">
        <div class="card-head">
          SIP 信令时序
          <span class="count-badge">{{ filteredSip.length }} 条</span>
          <span class="spacer"></span>
          <select v-model="filterMethod" class="mini-select">
            <option value="">全部方法</option>
            <option v-for="m in methods" :key="m" :value="m">{{ m }}</option>
          </select>
          <input v-model="filterCallId" class="mini-input" placeholder="Call-ID 过滤" />
          <button class="btn-mini" @click="downloadSvg">导出 SVG</button>
        </div>
        <div class="card-body timeline-body">
          <div class="tl-scroll">
            <svg id="sip-timeline" class="tl-svg" :viewBox="`0 0 1000 ${TIMELINE_H}`"
                 :style="{ height: TIMELINE_H + 'px' }">
              <!-- 参与方竖线 -->
              <g v-for="ip in SIG_ROLES" :key="ip">
                <line :x1="laneX(ip)" y1="34" :x2="laneX(ip)" :y2="TIMELINE_H - 14"
                      stroke="var(--line-2)" stroke-width="1" stroke-dasharray="3 3" />
                <text :x="laneX(ip)" y="22" text-anchor="middle"
                      fill="var(--text-3)" font-size="10.5" font-family="monospace">{{ ip }}</text>
              </g>

              <!-- 消息箭头 -->
              <g v-for="(m, i) in filteredSip" :key="m.id"
                 @click="selectMsg(m)" style="cursor:pointer">
                <rect x="0" :y="44 + i * 26 - 10" width="1000" height="24"
                      :fill="selectedMsg?.id === m.id ? 'var(--ds-soft)' : 'transparent'" />
                <line
                  :x1="laneX(m.source_ip || SIG_ROLES[0])"
                  :y1="44 + i * 26"
                  :x2="laneX(m.destination_ip || SIG_ROLES[1] || SIG_ROLES[0])"
                  :y2="44 + i * 26"
                  :stroke="m.is_request ? 'var(--ds)' : (String(m.status_code || '').startsWith('2') ? 'var(--ok)' : 'var(--critical)')"
                  stroke-width="1.4"
                  :marker-end="`url(#arr${m.is_request ? 'Req' : (String(m.status_code || '').startsWith('2') ? 'Ok' : 'Err')})`" />
                <text :x="laneX(m.source_ip || SIG_ROLES[0])" :y="40 + i * 26"
                      text-anchor="middle" fill="var(--text-3)" font-size="10" font-family="monospace">
                  {{ m.is_request ? m.method : m.status_code }}
                </text>
                <text x="995" :y="47 + i * 26" text-anchor="end"
                      fill="var(--text-4)" font-size="10" font-family="var(--font-mono)">
                  {{ m.timestamp.toFixed(3) }}s
                </text>
              </g>

              <defs>
                <marker id="arrReq" viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--ds)"/>
                </marker>
                <marker id="arrOk" viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--ok)"/>
                </marker>
                <marker id="arrErr" viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--critical)"/>
                </marker>
              </defs>
            </svg>
          </div>
          <div v-if="!filteredSip.length" class="empty">
            该会话没有关联到 SIP 消息
          </div>
        </div>
      </div>

      <!-- 媒体指标 -->
      <div class="grid-2 mb-16">
        <div class="card">
          <div class="card-head">媒体码率趋势</div>
          <div class="chart-md" id="chart-bitrate"></div>
          <div v-if="!metrics.some(m => m.bitrate_series?.length)" class="empty">
            无媒体流，无法计算码率
          </div>
        </div>
        <div class="card">
          <div class="card-head">RTP 抖动趋势（RFC 3550）</div>
          <div class="chart-md" id="chart-jitter"></div>
          <div v-if="!metrics.some(m => m.jitter_series?.length)" class="empty">
            无媒体流，无法计算抖动
          </div>
        </div>
      </div>

      <!-- 媒体流列表 -->
      <div class="card mb-16">
        <div class="card-head">
          媒体流
          <span class="count-badge">{{ streams.length }}</span>
        </div>
        <div class="card-body tight">
          <table class="tbl" v-if="streams.length">
            <thead>
              <tr>
                <th>SSRC</th><th>传输</th><th>端口</th><th>包数</th>
                <th>时长</th><th>码率</th><th>抖动</th><th>序号缺口</th>
                <th>乱序</th><th>最大静默</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="st in streams" :key="st.id">
                <td class="mono">{{ st.ssrc ? '0x' + st.ssrc.toString(16).padStart(8,'0') : '—' }}</td>
                <td><span class="proto">{{ st.transport }}</span></td>
                <td class="mono-sm">{{ st.source_port }} → {{ st.destination_port }}</td>
                <td class="num">{{ st.packet_count }}</td>
                <td class="num">{{ fmt(st.duration, 2) }}s</td>
                <td class="num">{{ st.avg_bitrate != null ? fmt(st.avg_bitrate, 0) + ' kbps' : '—' }}</td>
                <td class="num" :class="st.jitter_avg > 50 ? 'text-warning' : ''">
                  {{ st.jitter_avg != null ? fmt(st.jitter_avg, 2) + ' ms' : '—' }}
                </td>
                <td class="num" :class="st.seq_gap_packets ? 'text-critical' : ''">
                  {{ st.seq_gap_packets }}
                </td>
                <td class="num">{{ st.out_of_order_count }}</td>
                <td class="num" :class="st.max_gap > 3 ? 'text-warning' : ''">
                  {{ st.max_gap != null ? fmt(st.max_gap, 2) + 's' : '—' }}
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">
            未发现该会话的媒体流
            <div class="hint">可能是媒体未经过抓包点，或媒体端口未建立连接</div>
          </div>
        </div>
      </div>

      <!-- 诊断 -->
      <div class="card mb-16">
        <div class="card-head">
          诊断结论
          <span class="count-badge">{{ diagnostics.length }}</span>
        </div>
        <div class="card-body">
          <div v-if="diagnostics.length" class="diag-list">
            <div v-for="d in diagnostics" :key="d.id" class="diag" :class="d.severity">
              <div class="diag-head">
                <span class="badge" :class="d.severity">{{ d.severity }}</span>
                <span class="diag-rule mono">{{ d.rule_id }}</span>
                <span class="diag-title">{{ d.title }}</span>
                <span class="spacer"></span>
                <span class="badge" :class="d.evidence_level === 'confirmed' ? 'ok' : (d.evidence_level === 'suspected' ? 'warning' : 'unknown')">
                  {{ { confirmed: '已确认', suspected: '疑似', insufficient: '证据不足' }[d.evidence_level] }}
                </span>
              </div>
              <div class="diag-desc">{{ d.description }}</div>
              <div v-if="d.possible_causes?.length" class="diag-block">
                <div class="diag-label">可能原因</div>
                <ul><li v-for="(c, i) in d.possible_causes" :key="i">{{ c }}</li></ul>
              </div>
              <div v-if="d.recommendations?.length" class="diag-block">
                <div class="diag-label">建议排查</div>
                <ul><li v-for="(c, i) in d.recommendations" :key="i">{{ c }}</li></ul>
              </div>
              <div v-if="d.related_packet_ids?.length" class="diag-block">
                <div class="diag-label">关联报文</div>
                <div class="row" style="gap:6px;flex-wrap:wrap">
                  <a v-for="p in d.related_packet_ids.slice(0, 10)" :key="p"
                     class="pkt-link mono" @click="gotoPacket(p)">#{{ p }}</a>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty">
            未发现异常
            <div class="hint">规则引擎未在该会话中检测到问题</div>
          </div>
        </div>
      </div>

      <!-- 选中消息详情 -->
      <div v-if="selectedMsg" class="card">
        <div class="card-head">
          报文详情 · #{{ selectedMsg.packet_id }}
          <span class="spacer"></span>
          <button class="btn-mini" @click="gotoPacket(selectedMsg.packet_id)">在报文中查看</button>
          <button class="btn-mini" @click="selectedMsg = null">关闭</button>
        </div>
        <div class="card-body">
          <div class="msg-grid">
            <div><span>方法</span><b class="mono">{{ selectedMsg.method || selectedMsg.status_code }}</b></div>
            <div><span>Call-ID</span><b class="mono truncate">{{ selectedMsg.call_id || '—' }}</b></div>
            <div><span>From Tag</span><b class="mono">{{ selectedMsg.from_tag || '—' }}</b></div>
            <div><span>To Tag</span><b class="mono">{{ selectedMsg.to_tag || '—' }}</b></div>
            <div><span>CSeq</span><b class="mono">{{ selectedMsg.cseq || '—' }}</b></div>
            <div><span>源</span><b class="mono">{{ selectedMsg.source_ip }}:{{ selectedMsg.source_port }}</b></div>
            <div><span>目的</span><b class="mono">{{ selectedMsg.destination_ip }}:{{ selectedMsg.destination_port }}</b></div>
            <div><span>国标命令</span><b>{{ selectedMsg.gb_command || '—' }}</b></div>
          </div>
          <div v-if="selectedMsg.sdp" class="sdp-block">
            <div class="diag-label">SDP</div>
            <div class="sdp-grid">
              <div><span>连接地址</span><b class="mono">{{ selectedMsg.sdp.connection_address || '—' }}</b></div>
              <div><span>媒体</span><b class="mono">
                {{ (selectedMsg.sdp.media || []).map(m => `${m.type}/${m.port}/${m.protocol}`).join(', ') || '—' }}
              </b></div>
              <div><span>setup</span><b class="mono">{{ selectedMsg.sdp.setup || '—' }}</b></div>
              <div><span>y= SSRC</span><b class="mono">{{ selectedMsg.sdp.y_ssrc || '—' }}</b></div>
              <div><span>方向</span><b>{{ selectedMsg.sdp.stream_mode || '—' }}</b></div>
            </div>
          </div>
          <div v-if="selectedMsg.body_preview" class="body-block">
            <div class="diag-label">正文</div>
            <pre class="body-pre">{{ selectedMsg.body_preview }}</pre>
          </div>
        </div>
      </div>
    </template>

    <div v-else-if="loading" class="empty">加载中…</div>
  </div>
</template>

<style scoped>
.event-timeline { list-style: none; padding: 8px 18px 16px; }
.event-timeline li { display: grid; grid-template-columns: 76px 10px minmax(0,1fr) auto; gap: 12px; align-items: baseline; padding: 10px 0; border-bottom: 1px solid var(--line); }
.event-timeline li:last-child { border-bottom: 0; }
.event-time { color: var(--text-3); font-size: 12px; }
.event-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--flow); }
.event-dot.warning { background: var(--warning); }
.event-dot.critical { background: var(--critical); }
.event-content { min-width: 0; overflow-wrap: anywhere; }
.event-content p { color: var(--text-2); font-size: 12px; }
@media (max-width: 600px) { .event-timeline li { grid-template-columns: 62px 8px minmax(0,1fr); gap: 8px; } .event-timeline button { grid-column: 3; justify-self: start; } }
.h1 { font-size: 19px; font-weight: 600; }
.sub { font-size: 12px; color: var(--text-3); margin-top: 3px; }
.sep { color: var(--text-4); margin: 0 5px; }


.kpi-mono {
  font-family: var(--font-mono); font-size: 13px;
  color: var(--text); margin-top: 3px; word-break: break-all;
}

.param-grid, .msg-grid, .sdp-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px 22px;
}
.msg-grid > div, .sdp-grid > div {
  display: flex; gap: 10px; font-size: 12.5px; align-items: baseline;
}
.msg-grid span, .sdp-grid span {
  color: var(--text-3); width: 84px; flex: none; font-size: 12px;
}
.msg-grid b, .sdp-grid b { color: var(--text-2); font-weight: 500; }

/* 协商参数：像仪表铭牌一样成列，而不是一串漂浮的标签 */
.param-grid {
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 0 26px;
  border-top: 1px solid var(--line);
}
.param {
  display: flex; flex-direction: column; gap: 3px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.param span { color: var(--text-4); width: auto; font-size: 11.5px; }
.param b { color: var(--text); font-weight: 500; font-size: 13px; font-family: var(--font-mono); }

.ssrc-warn {
  margin-top: 12px; padding: 9px 12px;
  background: var(--warning-bg); border-left: 2px solid var(--warning);
  border-radius: var(--radius-sm); font-size: 12px; color: var(--warning);
}

.count-badge {
  font-size: 12px; padding: 1px 7px; border-radius: 99px;
  background: var(--surface-3); color: var(--text-3);
}

.mini-select, .mini-input {
  height: 26px; padding: 0 8px;
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); color: var(--text-2);
  font-size: 12px; font-family: inherit;
}
.mini-input { width: 130px; }
.mini-select:focus, .mini-input:focus { outline: none; border-color: var(--accent); }


.timeline-body { padding: 0; }
.tl-scroll { max-height: 420px; overflow: auto; }
.tl-svg { width: 100%; display: block; }

.chart-md { height: 240px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1280px) { .grid-2 { grid-template-columns: 1fr; } }

.diag-list { display: flex; flex-direction: column; gap: 12px; }
.diag {
  background: transparent; border-radius: 0;
  padding: 12px 0 12px 13px; border-left: 2px solid var(--text-4);
  border-top: 1px solid var(--line);
}
.diag:last-child { border-bottom: 1px solid var(--line); }
.diag.critical { border-left-color: var(--critical); }
.diag.warning { border-left-color: var(--warning); }
.diag.info { border-left-color: var(--info); }
.diag.unknown { border-left-color: var(--text-4); }

.diag-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.diag-rule { font-size: 12px; color: var(--text-3); }
.diag-title { font-size: 13px; font-weight: 600; }
.diag-desc { font-size: 12.5px; color: var(--text-2); margin-top: 7px; line-height: 1.7; }
.diag-block { margin-top: 9px; }
.diag-label {
  font-size: 11.5px; color: var(--text-4); margin-bottom: 4px;
}
.diag-block ul { margin-left: 18px; font-size: 12.5px; color: var(--text-2); line-height: 1.8; }

.pkt-link {
  font-family: var(--font-mono); font-size: 11.5px; padding: 1px 4px;
  color: var(--text-2); cursor: pointer;
  border-bottom: 1px solid var(--line-3);
}
.pkt-link:hover { color: var(--text); border-bottom-color: currentColor; }

.sdp-block, .body-block { margin-top: 14px; }
.body-pre {
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 12px;
  font-family: var(--font-mono); font-size: 12px;
  color: var(--text-2); max-height: 260px; overflow: auto;
  white-space: pre-wrap; word-break: break-all; line-height: 1.65;
}

.err-box {
  background: var(--critical-bg); border: 1px solid rgba(240,69,58,.35);
  border-left: 3px solid var(--critical); border-radius: var(--radius);
  padding: 14px 16px; font-size: 13px; color: var(--critical);
  margin-bottom: 16px;
}
</style>
