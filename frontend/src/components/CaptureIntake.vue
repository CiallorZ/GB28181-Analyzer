<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import MetricCard from './MetricCard.vue'
import InterfaceState from './InterfaceState.vue'

import { useTaskStore } from '../stores/task'

const store = useTaskStore()
const props = defineProps({
  busy: Boolean,
  progress: { type: Number, default: 0 },
  error: { type: String, default: '' }
})
const emit = defineEmits(['file', 'sample', 'recorded'])
const adapters = ref([])
const selectedAdapter = ref(null)
const seconds = ref(15)
const recording = ref(false)
const recordMsg = ref('')
async function loadAdapters() {
  try {
    const res = await fetch('/api/v1/intake/interfaces')
    const data = await res.json()
    if (!res.ok) throw Error(data.detail || '无法读取网卡')
    adapters.value = data
    selectedAdapter.value = data[0]?.id
    recordMsg.value = data.length ? '' : '未发现可采集网卡'
  } catch(e) { recordMsg.value = e.message }
}
async function record() {
  recording.value = true
  recordMsg.value = '正在采集，达到时长或 64 MiB 后自动结束。'
  try {
    const res = await fetch('/api/v1/intake/record', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interface:selectedAdapter.value,seconds:seconds.value})})
    const data = await res.json()
    if(!res.ok) throw Error(data.detail || '采集失败')
    await api.analyze(data.task_id)
    emit('recorded', data.task_id)
  } catch(e) { recordMsg.value = e.message }
  finally {recording.value = false}
}
const picker = ref(null)
const dragging = ref(false)
const history = ref(null)
const historyError = ref(false)
const status = {
  pending: ['待分析', 'unknown'], analyzing: ['分析中', 'info'],
  completed: ['已完成', 'ok'], failed: ['失败', 'critical'], cancelled: ['已取消', 'unknown']
}
const date = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' })
function localDate(value) {
  if (!value) return '—'
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + 'Z'
  return date.format(new Date(normalized))
}
const demoPaused = ref(false)
const exchange = [
  { name: 'INVITE', detail: '发起点播 · SDP offer', direction: 'request' },
  { name: '100 Trying', detail: '正在处理请求', direction: 'response', provisional: true },
  { name: '200 OK', detail: '接受请求 · SDP answer', direction: 'response' },
  { name: 'ACK', detail: '确认会话', direction: 'request' },
  { name: 'RTP', detail: '发送媒体', direction: 'media' },
  { name: 'BYE', detail: '结束会话', direction: 'request' },
  { name: '200 OK', detail: '确认结束', direction: 'response' }
]
const binary = ['01101001 00011010 10110100 01011001', '10100110 01011100 00100011 10010010']
const latest = computed(() => history.value?.find(task => task.status === 'completed'))
const total = ref(null)
const metrics = computed(() => {
  const completed = (history.value || []).filter(task => task.status === 'completed').reverse()
  return [
    { label: '任务总数', value: total.value, icon: 'history' },
    ...[['最近完成任务 · 报文', 'packet_count', 'file'], ['业务会话', 'session_count', 'signal'], ['诊断事件', 'diagnostic_count', 'warning']].map(([label, key, icon]) => ({
      label, icon, value: latest.value?.[key], samples: completed.map(task => task[key])
    }))
  ]
})
const points = computed(() => {
  const tasks = (history.value || []).filter(task => task.status === 'completed' && task.packet_count != null).slice().reverse()
  const max = Math.max(1, ...tasks.map(task => task.packet_count))
  return tasks.map((task, i) => ({
    task, x: tasks.length === 1 ? 250 : 16 + i * 468 / (tasks.length - 1),
    y: 101 - task.packet_count * 88 / max
  }))
})
const inspectedId = ref(null)
const inspected = computed(() => points.value.find(p => p.task.id === inspectedId.value) || points.value.at(-1))
const line = computed(() => points.value.map(p => p.x + ',' + p.y).join(' '))
const area = computed(() => points.value.length ? points.value[0].x + ',108 ' + line.value + ' ' + points.value.at(-1).x + ',108' : '')
async function loadHistory() {
  historyError.value = false
  total.value = null
  history.value = null
  try {
    const page = await api.tasks({ page_size: 8 })
    total.value = page.total
    history.value = page.items
  } catch {
    historyError.value = true
  }
}
onMounted(loadHistory)

function pick(event) {
  if (event.target.files[0]) emit('file', event.target.files[0])
  event.target.value = ''
}

function drop(event) {
  dragging.value = false
  if (props.busy) return
  if (event.dataTransfer.files[0]) emit('file', event.dataTransfer.files[0])
}
</script>

<template>
  <div class="capture-home page-content-in" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.self.prevent="dragging = false" @drop.prevent="drop">
    <header class="mast">
      <h1>工作台</h1>
      <div class="metrics" aria-label="任务总数与最近完成任务指标">
        <MetricCard v-for="metric in metrics" :key="metric.label" v-bind="metric" />
      </div>
      <small v-if="latest">近期任务中最近完成 · {{ latest.name }}</small>
    </header>
    <div class="dashboard">
      <section class="panel trend">
        <header><h2>报文量趋势</h2><small>最近 8 个任务中的已完成任务</small></header>
        <div v-if="points.length" class="plot">
          <div v-if="inspected" class="plot-readout"><strong>{{ inspected.task.packet_count.toLocaleString() }} <small>个报文</small></strong><span>{{ inspected.task.name }}</span></div>
          <svg viewBox="0 0 500 114" preserveAspectRatio="none" role="img" aria-label="按任务创建顺序排列的报文量，详细数量见下表">
            <defs><linearGradient id="volume-fill" x2="0%" y2="100%"><stop stop-color="var(--chart-primary)" stop-opacity=".25"/><stop offset="1" stop-color="var(--chart-primary)" stop-opacity="0"/></linearGradient></defs>
            <path d="M0 14H500 M0 45H500 M0 76H500 M0 107H500" stroke="var(--line)" fill="none" stroke-dasharray="3 4"/>
            <polygon :points="area" fill="url(#volume-fill)"/>
            <polyline pathLength="1" :points="line" stroke="var(--chart-primary)" fill="none" stroke-width="2" vector-effect="non-scaling-stroke"/>
            <line v-if="inspected" :x1="inspected.x" :x2="inspected.x" :y1="inspected.y" y2="108" stroke="var(--chart-primary)" stroke-dasharray="2 4" opacity=".55" />
            <circle v-for="p in points" :key="p.task.id" :cx="p.x" :cy="p.y" r="3" fill="var(--chart-primary)"><title>{{ p.task.name }} · {{ p.task.packet_count }} 个报文</title></circle>
          </svg>
          <div class="axis" aria-label="选择任务查看报文量"><button v-for="p in points" :key="p.task.id" :aria-label="'查看 '+p.task.name+' 的报文量'" :aria-pressed="inspected?.task.id === p.task.id" @click="inspectedId = p.task.id" @focus="inspectedId = p.task.id">#{{ p.task.id }}</button></div>
        </div>
        <InterfaceState v-else :kind="historyError ? 'error' : history === null ? 'loading' : 'empty'" :title="historyError ? '趋势读取失败' : history === null ? '读取任务中…' : '完成抓包分析后显示趋势'" icon="wave" />
      </section>
      <section class="panel actions">
        <h2>快捷操作</h2>
        <input ref="picker" type="file" accept=".pcap,.pcapng,.cap" hidden @change="pick">
        <button class="btn primary" :disabled="busy" @click="picker.click()"><AppIcon name="upload"/>{{ busy ? '正在导入 '+progress+'%' : dragging ? '松开以导入' : '新建分析任务' }}</button>
        <button class="btn" :disabled="busy" @click="emit('sample')"><AppIcon name="file"/>导入示例抓包</button>
        <router-link class="btn" to="/compare"><AppIcon name="compare"/>双包对比</router-link>
        <button class="btn ai-entry" @click="store.openAiPanel()"><img src="/brand/deepseek.svg" alt="" width="18">DeepSeek 专家会诊</button>
        <details class="live"><summary>从本机网卡采集</summary><button class="btn" @click="loadAdapters" :disabled="recording">读取网卡</button>
          <template v-if="adapters.length"><select v-model="selectedAdapter" aria-label="采集网卡"><option v-for="a in adapters" :key="a.id" :value="a.id">{{a.name}}</option></select><label>时长（秒）<input type="number" v-model.number="seconds" min="1" max="120"></label><button class="btn" @click="record" :disabled="recording || busy">开始采集</button></template>
          <p role="status">{{recordMsg}}</p></details>

        <progress v-if="busy" :value="progress" max="100" aria-label="抓包导入进度"/>
        <p v-if="error" role="alert" class="err-box">{{ error }}</p>
      </section>
    </div>
    <section class="panel recent">
      <header><h2>最近任务</h2><router-link to="/tasks">全部任务 →</router-link></header>
      <InterfaceState v-if="historyError" kind="error" title="无法读取任务"><button class="btn" @click="loadHistory">重试</button></InterfaceState>
      <InterfaceState v-else-if="!history" kind="loading" title="正在读取历史任务…"/>
      <InterfaceState v-else-if="!history.length" title="还没有分析任务" detail="拖入 PCAP、PCAPNG 或 CAP 文件开始分析。" icon="history"/>
      <div v-else class="table-scroll"><table class="tbl"><thead><tr><th>任务名称</th><th>报文数</th><th>会话</th><th>创建时间</th><th>状态</th></tr></thead>
        <tbody><tr v-for="task in history" :key="task.id"><td><router-link :to="{name:'task',params:{id:task.id}}">{{ task.name }}</router-link></td><td>{{ task.packet_count?.toLocaleString() ?? '—' }}</td><td>{{ task.session_count ?? '—' }}</td><td>{{ localDate(task.created_at) }}</td><td><span class="badge" :class="status[task.status]?.[1]">{{ status[task.status]?.[0] || task.status }}</span></td></tr></tbody>
      </table></div>
    </section>
    <details class="panel demonstration"><summary>点播信令流程演示</summary>
      <figure class="exchange" :class="{ paused: demoPaused }" aria-labelledby="exchange-title">
        <div class="binary-field" aria-hidden="true">
          <span v-for="i in 8" :key="i" :style="{ '--lane': i }">{{ (binary[i % 2] + '   ').repeat(13) }}</span>
        </div>
        <figcaption class="exchange-head">
          <div><h2 id="exchange-title">点播信令交互</h2><p>协议流程演示 · SIP / SDP / RTP</p></div>
          <button class="motion-toggle" type="button" @click="demoPaused = !demoPaused">
            <AppIcon :name="demoPaused ? 'play' : 'pause'" />
            {{ demoPaused ? '继续演示' : '暂停演示' }}
          </button>
        </figcaption>
        <div class="endpoints">
          <span><AppIcon name="monitor" />点播平台</span>
          <span><AppIcon name="codec" />前端设备</span>
        </div>
        <ol class="exchange-rows">
          <li v-for="(message, i) in exchange" :key="i" :class="[message.direction, { provisional: message.provisional }]" :style="{ '--delay': i * 1.55 + 's' }">
            <div class="message"><b>{{ message.name }}</b><span>{{ message.detail }}</span></div>
            <span class="sr-only">{{ message.direction === 'request' ? '平台发往设备' : '设备发往平台' }}</span>
            <div class="wire" aria-hidden="true"><span></span></div>
          </li>
        </ol>
      </figure>
    </details>
  </div>
</template>

<style scoped>
.capture-home { display:grid; gap:14px; padding-block:4px 24px; }
.capture-home.dragging { outline:2px dashed var(--brand); outline-offset:4px; }
.mast { padding:20px; border-radius:var(--radius-lg); background:url('/brand/tower-lines.svg') right center / auto 140% no-repeat,linear-gradient(106deg,var(--surface) 43%,var(--bg-selected)); border:1px solid var(--line); }
.mast h1 { margin:0 0 14px; }
.metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; max-width:86%; }
small,.axis { color:var(--text-3); font-size:12px; }
.mast small { display:block; margin-top:9px; overflow-wrap:anywhere; }
.dashboard { display:grid; grid-template-columns:minmax(0,1fr) minmax(200px,26%); gap:14px; }
.panel { min-width:0; padding:16px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); }
.panel header,.axis { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.panel h2 { font-size:15px; margin:0; }
.panel header a { font-size:12px; color:var(--brand-lt); }
.trend { display:flex; flex-direction:column; }
.plot { margin-top:18px; flex:1; display:flex; flex-direction:column; }
.plot svg { width:100%; min-height:115px; flex:1; }
.actions { display:grid; align-content:start; gap:7px; }
.actions .btn { width:100%; justify-content:center; }
.actions .ai-entry { color:var(--ds-lt); background:var(--ds-soft); border-color:var(--ds-line); }
.live { font-size:12px; color:var(--text-2); }
.live[open] > * { margin-block:5px; max-width:100%; }
summary { cursor:pointer; }
.table-scroll { overflow:auto; margin-top:12px; }
.tbl td:first-child a { color:var(--text); font-weight:600; }
.tbl td:first-child a:hover { color:var(--brand-lt); }
.demonstration { font-size:13px; }
.exchange { margin:12px 0 0; max-width:680px; }
.exchange-head,.endpoints,.message { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.endpoints { margin-top:14px; }
.exchange-rows { list-style:none; padding:0; }
.motion-toggle { color:var(--text); background:var(--surface-2); border:1px solid var(--line); border-radius:var(--radius-sm); padding:6px; }
.binary-field { display:none; }
@media(max-width:800px){.metrics{max-width:100%;grid-template-columns:repeat(2,minmax(0,1fr))}.dashboard{grid-template-columns:1fr}.mast{padding:14px}}
@media(prefers-reduced-motion:reduce){.exchange .wire span{animation:none}.motion-toggle{display:none}}
.exchange-rows li { position:relative; --signal:var(--info); }
.exchange-rows .response { --signal:var(--ok); }
.exchange-rows .media { --signal:var(--brand-lt); }
.message { padding:8px 13px 4px; font-size:12px; }
.message b { font:650 12px var(--font-mono); color:var(--signal); }
.message span { color:var(--text-2); text-align:right; }
.wire {
  position:relative;
  margin:0 4px;
  height:8px;
  background:linear-gradient(90deg,var(--signal),var(--signal)) center / 100% 1px no-repeat;
}
.response .wire,.media .wire { transform:scaleX(-1); }
.wire::after {
  content:'';
  position:absolute;
  top:1px;
  right:0;
  width:6px;
  height:6px;
  border-top:1px solid var(--signal);
  border-right:1px solid var(--signal);
  transform:rotate(45deg);
}
.wire span {
  position:absolute;
  top:1px;
  width:21px;
  max-width:12%;
  height:6px;
  border-radius:12px;
  background:linear-gradient(90deg,transparent,var(--signal));
  box-shadow:0 0 9px color-mix(in srgb,var(--signal) 55%,transparent);
  left:0;
  opacity:0;
  animation:signal-pulse 7s linear infinite var(--delay);
}
@keyframes signal-pulse {
  0% { opacity:0; left:0; }
  3% { opacity:1; }
  18% { opacity:1; }
  21%,100% { opacity:0; left:94%; }
}
.paused .wire span { animation-play-state:paused; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.capture-home .mast { position:relative; isolation:isolate; overflow:hidden; background:linear-gradient(105deg,var(--mast-start) 18%,var(--mast-end)); border:1px solid var(--mast-line); padding:clamp(18px,2vw,30px); }
.mast::before { content:''; position:absolute; inset:0; z-index:-1; background:url('/brand/tower-lines.svg') right center / auto 130% no-repeat; filter:var(--tower-filter); opacity:var(--tower-opacity); }
.capture-home .mast h1 { color:var(--text); font-size:clamp(24px,2.1vw,32px); font-weight:700; margin-bottom:15px; }
.mast .metrics { gap:8px; max-width:89%; }
.mast small { color:var(--text-2); }
.plot-readout { display:flex; flex-wrap:wrap; align-items:baseline; gap:9px; margin-bottom:8px; }
.plot-readout strong { font-size:20px; font-variant-numeric:tabular-nums; }.plot-readout span { color:var(--text-3);font-size:12px; overflow-wrap:anywhere; }
.axis button { background:transparent; color:var(--text-3); border:0; border-radius:5px; padding:4px 6px; font:12px var(--font-mono); cursor:pointer; }
.axis button[aria-pressed=true] { color:var(--brand-lt); background:var(--bg-selected); }
@media(max-width:800px){.mast .metrics{max-width:100%}}
</style>
