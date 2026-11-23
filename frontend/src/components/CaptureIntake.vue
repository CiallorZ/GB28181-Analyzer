<script setup>
import { onMounted, ref } from 'vue'
import PlaybackIllustration from './PlaybackIllustration.vue'
import { api } from '../api/client'

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
const layers = [
  { icon: 'signal', code: 'SIP / SDP', name: '信令与协商', detail: '点播时序 · 响应码 · 端口与 SSRC' },
  { icon: 'wave', code: 'RTP / TCP', name: '媒体传输', detail: '序号缺口 · 抖动 · 码率趋势' },
  { icon: 'codec', code: 'PS / ES', name: '封装与编码', detail: 'H.264 / H.265 · 画面重建' }
]

onMounted(async () => {
  try {
    history.value = (await api.tasks({ page_size: 4 })).items
  } catch {
    historyError.value = true
  }
})

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
  <div class="capture-home">
    <section class="hero glass-panel" aria-labelledby="hero-title">
      <div class="hero-copy" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
        <div class="hero-meta"><img src="/brand/analyzer.svg" width="30" height="30" alt="">中国铁塔 · 视联网</div>
        <h1 id="hero-title">抓包分析工作台</h1>
        <p>拖入抓包，沿点播会话检查信令、媒体传输与重建画面。</p>
        <div class="drop-surface"><strong>导入抓包</strong><div class="hero-actions">
          <input ref="picker" type="file" accept=".pcap,.pcapng,.cap" hidden @change="pick" />
          <button class="upload-button" type="button" :disabled="busy" @click="picker.click()">
            <AppIcon name="upload" />
            {{ busy ? `正在导入 ${progress}%` : dragging ? '松开以导入' : '选择抓包文件' }}
          </button>
          <button type="button" class="sample-button" :disabled="busy" @click="emit('sample')">试用示例抓包 <span aria-hidden="true"><AppIcon name="open" /></span></button>
        </div>
        </div>
        <details class="live"><summary>从本机网卡采集</summary><button class="btn" @click="loadAdapters" :disabled="recording">读取网卡</button>
          <template v-if="adapters.length"><select v-model="selectedAdapter" aria-label="采集网卡"><option v-for="a in adapters" :key="a.id" :value="a.id">{{a.name}}</option></select><label>时长（秒）<input type="number" v-model.number="seconds" min="1" max="120"></label><button class="btn" @click="record" :disabled="recording || busy">开始采集</button></template>
          <p role="status">{{recordMsg}}</p></details>
        <progress v-if="busy" :value="progress" max="100" aria-label="抓包导入进度"></progress>
        <div class="hero-note">支持 PCAP / PCAPNG / CAP <span></span> 抓包由分析服务所在设备处理</div>
        <div v-if="error" class="hero-error" role="alert">{{ error }}</div>
      </div>
      <PlaybackIllustration />
    </section>
    <section class="workspace" aria-label="分析路径与历史任务">
      <div class="workspace-body">
        <section class="layers" aria-labelledby="layers-title"><div class="section-head"><div><h2 id="layers-title">协议分析路径</h2></div><router-link to="/compare" class="all-link">双包对比 <AppIcon name="open" /></router-link></div>
          <ol class="layer-list"><li v-for="layer in layers" :key="layer.code"><span class="layer-icon"><AppIcon :name="layer.icon" /></span><div><strong>{{ layer.name }}</strong><p>{{ layer.detail }}</p></div><span class="layer-code">{{ layer.code }}</span></li></ol>
        </section>
        <section class="recent" aria-labelledby="recent-title"><div class="section-head"><div><h2 id="recent-title">最近分析</h2></div><router-link to="/tasks" class="all-link">全部任务 <span aria-hidden="true"><AppIcon name="forward" /></span></router-link></div>
          <p v-if="historyError" class="history-empty">历史记录暂时无法读取。</p><p v-else-if="history === null" class="history-empty" role="status">正在读取历史记录…</p><p v-else-if="!history.length" class="history-empty">导入首份抓包后，任务会出现在这里。</p>
          <ul v-else class="history-list"><li v-for="item in history" :key="item.id"><router-link :to="{ name: 'task', params: { id: item.id } }"><span class="file-icon" aria-hidden="true"><AppIcon name="file" /></span><span class="file-info"><strong class="truncate" :title="item.name">{{ item.name }}</strong><time :datetime="item.created_at">{{ localDate(item.created_at) }}</time></span><span class="badge" :class="status[item.status]?.[1]">{{ status[item.status]?.[0] || item.status }}</span><span class="row-arrow" aria-hidden="true"><AppIcon name="open" /></span></router-link></li></ul>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.capture-home { max-width:1500px; margin:auto; padding:28px 28px 64px; }
.hero { min-height:370px; position:relative; overflow:hidden; display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,.95fr); background:color-mix(in srgb,var(--surface) 84%,transparent); border:1px solid var(--line-2); border-radius:14px; color:var(--text); backdrop-filter:blur(20px); box-shadow:var(--shadow); }
.hero::after { z-index:-1; content:''; position:absolute; inset:0; pointer-events:none; background:repeating-linear-gradient(90deg,transparent 0 95px,var(--grid-line) 96px); }
.hero-copy { z-index:1; padding:32px clamp(24px,3vw,48px); }
.hero-meta { font-size:12px; font-weight:600; letter-spacing:.04em; color:var(--brand-lt); display:flex; align-items:center; gap:9px; }
.hero-mark { width:18px; height:2px; background:var(--brand); }
.hero h1 { margin:22px 0 12px; font-size:clamp(39px,4.4vw,64px); line-height:1.12; letter-spacing:-.045em; font-weight:750; }

.hero-copy > p { color:var(--text-2); font-size:14px; line-height:1.8; max-width:440px; }
.hero-actions { display:flex; gap:12px; align-items:center; margin-top:27px; flex-wrap:wrap; }
.upload-button,.sample-button { min-height:42px; border-radius:5px; padding:0 17px; font:inherit; font-size:13px; font-weight:650; cursor:pointer; display:inline-flex; gap:9px; align-items:center; justify-content:center; transition:transform .18s,background .18s; }
.upload-button { background:var(--brand-dk); color:#fff; border:1px solid var(--brand-dk); }.upload-button svg { width:17px; height:17px; }.upload-button:hover:not(:disabled) { background:var(--brand); transform:translateY(-2px); }
.sample-button { background:var(--surface); color:var(--text); border:1px solid var(--line-2); }.sample-button:hover:not(:disabled) { background:var(--surface-3); }.sample-button span { margin-left:4px; }
.upload-button:disabled,.sample-button:disabled { opacity:.7; cursor:progress; }.hero progress { display:block; width:220px; max-width:100%; margin-top:14px; accent-color:var(--brand); }
.hero-note { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:19px; color:var(--text-3); font-size:11px; }.hero-note span { width:3px; height:3px; border-radius:50%; background:currentColor; }.hero-error { margin-top:12px; font-size:12px; color:var(--critical); font-weight:600; }
.hero-copy.dragging { background:var(--brand-soft); outline:2px dashed var(--brand); outline-offset:-6px; }
.drop-surface { margin-top:22px; padding:16px 18px; border:1px dashed var(--line-strong); border-radius:10px; background:var(--surface-2); }
.drop-surface strong {font-size:13px;color:var(--text-2)}.drop-surface .hero-actions{margin-top:9px}
.workspace-body { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:28px; margin-top:29px; }.layers,.recent { min-width:0; border-top:2px solid var(--line-strong); padding-top:16px; }.section-head { display:flex; justify-content:space-between; align-items:end; gap:12px; padding-bottom:15px; border-bottom:1px solid var(--line-2); }.section-label { display:block; color:var(--brand-lt); font-size:11px; font-weight:650; margin-bottom:5px; }.section-head h2 { font-size:19px; letter-spacing:-.02em; }.section-hint,.all-link { font-size:12px; color:var(--text-3); }.all-link { color:var(--brand-lt); font-weight:650; text-decoration:none; }.all-link:hover { text-decoration:underline; }
.layer-list,.history-list { list-style:none; }.layer-list li { display:grid; grid-template-columns:38px minmax(0,1fr) auto; gap:10px; align-items:center; padding:15px 0; border-bottom:1px solid var(--line); }.layer-icon { display:grid; place-items:center; width:32px; height:32px; font-size:17px; color:var(--brand-lt); background:var(--surface); border:1px solid var(--line-2); border-radius:8px; }.layer-list strong { font-size:13px; }.layer-list p { color:var(--text-3); font-size:11.5px; margin-top:2px; }.layer-code { font:11px var(--font-mono); color:var(--text-3); }
.history-list a { display:flex; align-items:center; gap:12px; min-height:64px; border-bottom:1px solid var(--line); color:var(--text); text-decoration:none; }.history-list a:hover { background:var(--surface-2); }.file-icon { width:34px; height:34px; display:grid; place-items:center; flex:none; color:var(--brand-lt); background:var(--brand-soft); border-radius:7px; }.file-icon svg { width:20px; height:20px; }.file-info { display:grid; gap:3px; min-width:0; flex:1; }.file-info strong { font-size:12.5px; }.file-info time,.history-empty { font-size:11px; color:var(--text-3); }.history-empty { padding:24px 0; }.row-arrow { color:var(--text-4); }
@media (max-width:850px) { .capture-home { padding:20px 16px 48px; }.hero { grid-template-columns:1fr; }.hero-copy { padding:36px 28px; }.exchange { border-inline-start:0; border-top:1px solid var(--line); }.workspace-body { grid-template-columns:1fr; gap:30px; } }
@media (max-width:480px) { .hero-copy { padding:32px 22px; }.hero h1 { font-size:clamp(26px,7.5vw,34px); text-wrap:balance; }.layer-code { font-size:10px; } }
@media (prefers-reduced-motion:reduce) { .upload-button,.sample-button { transition:none; }.upload-button:hover:not(:disabled) { transform:none; } }
.live{margin:14px 0;color:var(--text-2);font-size:13px}.live summary{cursor:pointer}.live select,.live input{max-width:100%;margin:6px;padding:5px}.live input{width:6em}</style>
