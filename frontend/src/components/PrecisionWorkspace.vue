<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import SipLadder from './SipLadder.vue'
import VideoPlayer from './VideoPlayer.vue'
import MetricScope from './MetricScope.vue'
import PacketsView from '../views/PacketsView.vue'

const p = defineProps({
  task: Object,
  overview: Object,
  sessions: Array,
  streams: Array,
  events: Array,
  metrics: Object,
  metricsError: Boolean,
  metricsPending: Boolean,
  packets: Array,
  packetTotal: Number,
  expanded: Boolean
})
defineEmits(['expand'])
const store = useTaskStore()
const wideScreen = window.matchMedia('(min-width: 1401px)')
const rail = ref(wideScreen.matches)
const railToggle = ref(null)
function fitSidebar(e) {
  rail.value = e.matches
}
onMounted(() => wideScreen.addEventListener('change', fitSidebar))
onUnmounted(() => wideScreen.removeEventListener('change', fitSidebar))
async function collapseSidebar() {
  rail.value = false
  await nextTick()
  railToggle.value?.focus()
}
const sessionId = ref(p.sessions[0]?.id),
  streamId = ref(p.streams.find((s) => s.rebuilt_path)?.id ?? p.streams[0]?.id)
const mediaId = ref(''),
  sip = ref([]),
  sipError = ref(''),
  busy = ref(false),
  selected = ref(null),
  method = ref('')
const severity = ref(''),
  evidence = ref(''),
  event = ref(null),
  interval = ref(null)
const names = {
  critical: '严重',
  warning: '警告',
  info: '信息',
  unknown: '未知',
  confirmed: '已确认',
  suspected: '疑似',
  insufficient: '证据不足'
}
const sum = computed(() => p.overview.summary || {})
const counts = computed(() => sum.value.diagnostics)
const first = computed(() => p.events[0])
const extraMetric = ref(null)
const extraPending = ref(false)
const extraError = ref(false)
const trendStreams = computed(() =>
  mediaId.value ? p.streams.filter(s => s.id === mediaId.value) : p.streams.slice(0, 12)
)
const chartMetrics = computed(() => extraMetric.value
  ? { ...p.metrics, [extraMetric.value.stream_id]: extraMetric.value }
  : p.metrics)
watch(mediaId, async (id, _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  extraError.value = false
  extraPending.value = false
  if (!id || p.streams.slice(0, 12).some(s => s.id === id) || extraMetric.value?.stream_id === id) return
  extraPending.value = true
  try {
    const result = await api.taskMetrics(p.task.id, [id])
    if (current) extraMetric.value = result.items[0] || null
  } catch {
    if (current) extraError.value = true
  } finally {
    if (current) extraPending.value = false
  }
})
const video = computed(() => p.streams.find((s) => s.id === streamId.value))
const fmt = (v, n = 1) => (v == null ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: n }))
const proto = computed(
  () =>
    [
      Object.keys(p.overview.method_distribution || {}).length || p.sessions.length ? 'SIP' : '',
      sip.value.some((m) => m.sdp) ? 'SDP' : '',
      p.streams.length ? 'RTP' : '',
      p.streams.some((s) => s.extra?.ps) ? 'PS' : ''
    ]
      .filter(Boolean)
      .join(' / ') || '—'
)
const kpis = computed(() => {
  const s = sum.value,
    mediaOnly = !s.session_count && p.streams.length
  return [
    ['file', '抓包报文', fmt(p.task.file?.packet_count, 0), '帧', '报文索引'],
    mediaOnly
      ? ['monitor', '重建预览', fmt(p.streams.filter((v) => v.rebuilt_path).length), '份', '本地视频']
      : ['signal', '业务会话', fmt(s.session_count), '个', 'GB/T 28181'],
    mediaOnly
      ? ['wave', '平均抖动', fmt(s.avg_jitter_ms), 'ms', '已观测媒体']
      : ['check', '信令成功率', s.session_count ? fmt(s.signal_success_rate) : '—', '%', '按业务会话统计'],
    ['wave', '发现媒体流', fmt(s.total_streams), '路', mediaOnly ? '未观察到点播会话' : 'RTP 媒体'],
    [
      'warning',
      '诊断事件',
      counts.value ? fmt(Object.values(counts.value).reduce((a, b) => a + b, 0)) : '—',
      '条',
      '规则引擎'
    ],
    mediaOnly
      ? [
          'codec',
          '视频编码',
          [...new Set(p.streams.map((v) => v.codec).filter(Boolean))].join('/') || '—',
          '',
          '源流编码'
        ]
      : ['history', '首媒体耗时', fmt(s.avg_first_media_latency, 3), 's', '已关联会话均值']
  ]
})
watch(
  sessionId,
  async (id, _, onCleanup) => {
    let active = true
    onCleanup(() => {
      active = false
    })
    selected.value = null
    sip.value = []
    sipError.value = ''
    method.value = ''
    if (!id) return
    busy.value = true
    try {
      const data = await api.sessionSip(id)
      if (active) sip.value = data.items
    } catch (e) {
      if (active) sipError.value = e.message
    } finally {
      if (active) busy.value = false
    }
  },
  { immediate: true }
)
const mediaSelection = () => {
  interval.value = null
  if (mediaId.value) streamId.value = mediaId.value
}
const kind = (m) => (m.is_request ? m.method : String(m.status_code))
const messages = computed(() => sip.value.filter((m) => !method.value || kind(m) === method.value))
watch(messages, (items) => {
  if (selected.value && !items.some((m) => m.id === selected.value.id)) selected.value = null
})
const filtered = computed(() =>
  p.events.filter(
    (d) =>
      (!severity.value || d.severity === severity.value) &&
      (!evidence.value || d.evidence_level === evidence.value) &&
      (!interval.value ||
        (d.timestamp != null && d.timestamp >= interval.value[0] && d.timestamp <= interval.value[1]))
  )
)
const pkt = (n) => ({ name: 'packets', query: { task: p.task.id, number: n } })
const evidencePanel = ref(null)
let evidenceTrigger
async function evidenceOf(d, trigger) {
  evidenceTrigger = trigger
  event.value = d
  await nextTick()
  evidencePanel.value?.focus({ preventScroll: true })
  evidencePanel.value?.scrollIntoView({
    block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  })
}
async function closeEvidence() {
  event.value = null
  await nextTick()
  if (evidenceTrigger?.isConnected) evidenceTrigger.focus()
}
watch(filtered, (items) => {
  if (event.value && !items.some((d) => d.id === event.value.id)) event.value = null
})
</script>
<template>
  <div class="station">
    <header class="context">
      <strong :title="task.file?.filename"
        ><AppIcon name="file" /> {{ task.file?.filename || task.name }}</strong
      >
      <span>{{ fmt(task.file?.file_size == null ? null : task.file.file_size / 1048576, 2) }} MiB</span
      ><span>{{ task.file?.capture_start?.replace('T', ' ') || '—' }}</span
      ><span>{{ fmt(task.file?.duration, 3) }} s</span><span>{{ proto }}</span>
      <router-link to="/tasks">任务 #{{ task.id }}</router-link
      ><span class="done">已完成 · {{ task.progress }}%</span>
      <button ref="railToggle" @click="rail = !rail" :aria-expanded="rail">{{ rail ? '收起助手' : '展开助手' }}</button>
    </header>
    <div class="station-layout page-content-in" :class="{ withRail: rail }">
      <div class="instrument-grid">
        <section class="instrument wide">
          <header>
            <h2>分析总览</h2>
            <button @click="$emit('expand')">{{ expanded ? '收起完整明细' : '完整分析明细' }}</button>
          </header>
          <section class="finding" :class="first?.severity" aria-labelledby="finding-title">
            <AppIcon :name="!first ? 'check' : ['critical', 'warning'].includes(first.severity) ? 'warning' : 'info'" />
            <div class="finding-copy">
              <h3 id="finding-title">分析结论</h3>
              <strong>{{ first?.title || '本次抓包未命中异常规则' }}</strong>
              <small v-if="first">{{ first.rule_id }} · {{ names[first.evidence_level] }} · {{ first.description }}</small>
              <small v-else>结论覆盖本次抓包的可见范围和现有诊断规则。</small>
            </div>
            <div class="finding-actions">
              <button v-if="first" @click="evidenceOf(first, $event.currentTarget)">查看证据 ›</button>
              <button type="button" class="finding-ai" @click="store.openAiPanel()">
                <img src="/brand/deepseek.svg" alt="" />DeepSeek 会诊
              </button>
            </div>
          </section>
          <div class="readings">
            <article v-for="[icon, label, v, u, note] in kpis" :key="label">
              <i><AppIcon :name="icon" /></i>
              <div>
                <label>{{ label }}</label
                ><strong
                  >{{ v }} <small>{{ u }}</small></strong
                ><small>{{ note }}</small>
              </div>
            </article>
          </div>
        </section>
        <section class="instrument">
          <header>
            <h2>SIP 信令分析</h2>
            <select v-if="sessions.length" v-model="sessionId" aria-label="信令会话">
              <option v-for="s in sessions" :key="s.id" :value="s.id">会话 #{{ s.id }}</option></select
            ><select v-model="method" aria-label="消息过滤">
              <option value="">全部消息</option>
              <option v-for="m in new Set(sip.map(kind))" :key="m">{{ m }}</option></select
            ><router-link :to="sessionId ? '/sessions/' + sessionId : '/sip'">详情 ↗</router-link>
          </header>
          <div v-if="busy || sipError" class="vacant">{{ sipError || '正在读取信令…' }}</div>
          <SipLadder v-else-if="messages.length" :messages="messages" :context-messages="sip" @select="selected = $event" />
          <div v-else class="vacant">当前会话范围内没有匹配的信令</div>
          <div v-if="selected" class="inspect">
            <b>{{ kind(selected) }} · CSeq {{ selected.cseq ?? '—' }}</b
            ><span class="mono">Call-ID {{ selected.call_id || '—' }}</span
            ><span>From tag {{ selected.from_tag || '—' }} → To tag {{ selected.to_tag || '—' }}</span
            ><span v-if="selected.sdp"
              >SDP {{ selected.sdp.connection_address }}
              {{ selected.sdp.media?.map((m) => m.port + '/' + m.protocol).join(' · ') }} · SSRC
              {{ selected.sdp.y_ssrc ?? '—' }}</span
            >
            <details v-if="selected.headers">
              <summary>原始 SIP 头域</summary>
              <pre>{{ JSON.stringify(selected.headers, null, 2) }}</pre>
            </details>
            <router-link v-if="selected.packet_id" :to="pkt(selected.packet_id)"
              >报文 #{{ selected.packet_id }} ↗</router-link
            >
          </div>
        </section>
        <section class="instrument">
          <header>
            <h2>媒体质量分析</h2>
            <select v-model="mediaId" aria-label="趋势媒体流" @change="mediaSelection">
              <option value="">{{ streams.length > 12 ? '对比前 12 条流' : '全部趋势流' }}</option>
              <option v-for="s in streams" :value="s.id" :key="s.id">
                #{{ s.id }} · {{ s.ssrc ?? '未知 SSRC' }}
              </option></select
            ><router-link to="/media">详情 ↗</router-link>
          </header>
          <MetricScope
            :metrics="chartMetrics"
            :streams="trendStreams"
            :stream-id="mediaId"
            :error="extraError || (metricsError && !extraMetric)"
            :pending="metricsPending || extraPending"
            @range="interval = $event"
            @stream="streamId = $event"
          />
        </section>
        <section class="instrument">
          <header>
            <h2>视频与编码</h2>
            <select v-model="streamId" v-if="streams.length" aria-label="视频媒体流">
              <option v-for="s in streams" :key="s.id" :value="s.id">
                #{{ s.id }} · {{ s.ssrc ?? '未知 SSRC' }}
              </option>
            </select>
          </header>
          <div v-if="video" class="video-facts">
            <VideoPlayer :key="video.id" :stream="video" />
            <dl>
              <template
                v-for="[k, v] in [
                  ['源流编码', video.codec],
                  ['分辨率', video.width && video.height ? video.width + ' × ' + video.height : null],
                  ['帧率', fmt(video.fps) + ' fps'],
                  ['平均码率', fmt(video.avg_bitrate) + ' kbps'],
                  ['关键帧', video.keyframe_count],
                  [
                    '关键帧字节间隔',
                    video.extra?.ps?.video?.keyframe_intervals?.length
                      ? video.extra.ps.video.keyframe_intervals.slice(0, 4).join(' / ') + ' B'
                      : null
                  ],
                  ['传输方式', video.transport],
                  ['序号缺口', video.seq_gap_packets],
                  ['SSRC', video.ssrc],
                  ['Profile', video.extra?.ps?.video?.profile ?? video.extra?.ps?.profile]
                ]"
                :key="k"
                ><dt>{{ k }}</dt>
                <dd>{{ v ?? '—' }}</dd></template
              >
            </dl>
          </div>
          <small v-if="interval && video" class="foot"
            >预览未提供原始 PTS 与抓包时间的映射，请使用播放器进度条定位。</small
          >
          <div v-if="!video" class="vacant">此次抓包未观察到可展示的媒体流</div>
        </section>
        <section id="station-events" class="instrument">
          <header>
            <h2>诊断事件</h2>
            <select v-model="severity" aria-label="严重等级">
              <option value="">全部等级</option>
              <option v-for="k in ['critical', 'warning', 'info', 'unknown']" :key="k" :value="k">
                {{ names[k] }}
              </option></select
            ><select v-model="evidence" aria-label="证据等级">
              <option value="">全部证据</option>
              <option v-for="k in ['confirmed', 'suspected', 'insufficient']" :key="k" :value="k">
                {{ names[k] }}
              </option></select
            ><router-link to="/diagnostics">全部 ↗</router-link>
          </header>
          <div v-if="event" ref="evidencePanel" class="inspect" role="region" aria-label="诊断证据" tabindex="-1" @keydown.esc.stop="closeEvidence">
            <button @click="closeEvidence">关闭证据</button><b>{{ event.rule_id }} · {{ event.title }}</b
            ><span>{{ event.description }}</span>
            <pre>{{ JSON.stringify(event.evidence, null, 2) }}</pre>
            <span v-for="c in event.possible_causes" :key="c">待验证 · {{ c }}</span
            ><span v-for="c in event.recommendations" :key="c">{{ c }}</span
            ><router-link v-if="event.session_id" :to="'/sessions/' + event.session_id"
              >会话 #{{ event.session_id }}</router-link
            ><span v-if="event.stream_id">流 #{{ event.stream_id }}</span
            ><router-link v-for="n in event.related_packet_ids" :key="n" :to="pkt(n)"
              >报文 #{{ n }}</router-link
            >
          </div>
          <div class="event-list">
            <table>
              <thead>
                <tr>
                  <th>时间 / s</th>
                  <th>级别</th>
                  <th>规则 / 事件</th>
                  <th>证据</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in filtered" :key="d.id">
                  <td>{{ fmt(d.timestamp, 3) }}</td>
                  <td>
                    <span class="badge" :class="d.severity">{{ names[d.severity] }}</span>
                  </td>
                  <td>
                    <button @click="evidenceOf(d, $event.currentTarget)">
                      <small>{{ d.rule_id }}</small
                      >{{ d.title }}
                    </button>
                  </td>
                  <td>{{ names[d.evidence_level] }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!filtered.length" class="vacant">已载入事件中无匹配记录</div>
          </div>
          <small class="foot">已载入 {{ events.length }} 条 · 当前显示 {{ filtered.length }} 条</small>
        </section>
        <section class="instrument wide analyzer-packets">
          <header>
            <h2>原始报文</h2>
            <router-link to="/packets">完整查看器 ↗</router-link>
          </header>
          <PacketsView embedded :seed="packets" :seed-total="packetTotal" :range="interval" />
        </section>
      </div>
      <aside v-if="rail" class="assist">
        <header>
          <img src="/brand/deepseek.svg" alt="" />
          <h2>AI 智能分析</h2>
          <button @click="collapseSidebar" aria-label="折叠 AI 助手">收起</button>
        </header>
        <section>
          <h3>规则结论</h3>
          <strong>{{ first?.title || '未发现规则命中异常' }}</strong>
          <p>
            {{ first ? names[first.evidence_level] + ' · ' + first.rule_id : '当前抓包范围内的规则结果。' }}
          </p>
        </section>
        <section>
          <h3>观测证据</h3>
          <p>信令 · {{ fmt(sum.session_count) }} 个业务会话</p>
          <p v-if="selected?.sdp">
            SDP · {{ selected.sdp.connection_address }} · SSRC {{ selected.sdp.y_ssrc ?? '—' }}
          </p>
          <p>
            媒体 · {{ streams.length }} 条流，{{
              streams.filter((s) => s.session_id != null).length
            }}
            条关联会话
          </p>
          <p>重建 · {{ streams.filter((s) => s.rebuilt_path).length }} 份视频预览</p>
          <button v-if="first" @click="evidenceOf(first, $event.currentTarget)">查看规则依据 ↗</button>
        </section>
        <section>
          <h3>下一步建议</h3>
          <ol v-if="first?.recommendations?.length">
            <li v-for="x in first.recommendations" :key="x">{{ x }}</li>
          </ol>
          <p v-else>当前规则未提供排查建议。</p>
        </section>
        <div class="rail-actions">
          <small>规则观察与 AI 推断分别展示</small
          ><button class="consult-action" @click="store.openAiPanel()">进入 DeepSeek 专家会诊 ↗</button>
        </div>
      </aside>
    </div>
    <footer class="station-footer">
      <span>任务 #{{ task.id }} · 报告导出</span
      ><a
        v-for="f in ['md', 'json', 'html', 'csv']"
        :key="f"
        :href="'/api/v1/tasks/' + task.id + '/report?format=' + f"
        download
        >{{ f.toUpperCase() }}</a
      ><router-link to="/">新建分析 ↗</router-link>
    </footer>
  </div>
</template>
<style src="../styles/workstation.css"></style>
