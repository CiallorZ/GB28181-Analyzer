<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

const props = defineProps({
  busy: Boolean,
  progress: { type: Number, default: 0 },
  error: { type: String, default: '' }
})
const emit = defineEmits(['file', 'sample'])
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
const step = ref(0)
const exchange = [
  ['INVITE', '平台请求点播，通过 SDP 提供媒体接收地址。', false],
  ['200 OK', '设备接受请求，返回协商后的媒体参数。', true],
  ['ACK', '平台确认最终响应，完成会话建立。', false],
  ['RTP / PS', '设备向协商地址发送封装视频的 RTP 报文。', true]
]
const layers = [
  { code: 'SIP / SDP', name: '信令与协商', detail: '点播时序 · 响应码 · 端口与 SSRC' },
  { code: 'RTP / TCP', name: '媒体传输', detail: '序号缺口 · 抖动 · 码率趋势' },
  { code: 'PS / ES', name: '封装与编码', detail: 'H.264 / H.265 · 画面重建' }
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
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero-copy" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
        <div class="hero-meta"><span class="hero-mark"></span>中国铁塔 · 视联网协议分析</div>
        <h1 id="hero-title">视联网抓包工作台</h1>
        <p>拖入抓包，沿点播会话检查信令、媒体传输与重建画面。</p>
        <div class="hero-actions">
          <input ref="picker" type="file" accept=".pcap,.pcapng,.cap" hidden @change="pick" />
          <button class="upload-button" type="button" :disabled="busy" @click="picker.click()">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {{ busy ? `正在导入 ${progress}%` : dragging ? '松开以导入' : '选择抓包文件' }}
          </button>
          <button type="button" class="sample-button" :disabled="busy" @click="emit('sample')">试用示例抓包 <span aria-hidden="true">↗</span></button>
        </div>
        <progress v-if="busy" :value="progress" max="100" aria-label="抓包导入进度"></progress>
        <div class="hero-note">支持 PCAP / PCAPNG / CAP <span></span> 抓包由分析服务所在设备处理</div>
        <div v-if="error" class="hero-error" role="alert">{{ error }}</div>
      </div>
      <section class="exchange" aria-label="点播交互示意">
        <header><h2>点播交互示意</h2><span>GB/T 28181</span></header>
        <div class="endpoints"><strong>平台</strong><strong>设备</strong></div>
        <div class="lanes">
          <button v-for="([code, , reverse], i) in exchange" :key="code" type="button"
            :aria-pressed="step === i" :class="{ reverse, chosen:step === i }" @click="step = i">
            <span class="wire" aria-hidden="true"></span><b>{{ code }}</b>
          </button>
        </div>
        <p aria-live="polite">{{ exchange[step][1] }}</p>
      </section>
    </section>
    <section class="workspace" aria-label="分析路径与历史任务">
      <div class="workspace-body">
        <section class="layers" aria-labelledby="layers-title"><div class="section-head"><div><span class="section-label">分析路径</span><h2 id="layers-title">一次抓包，多层证据</h2></div><span class="section-hint">逐层定位</span></div>
          <ol class="layer-list"><li v-for="(layer, i) in layers" :key="layer.code"><span class="layer-index">0{{ i + 1 }}</span><div><strong>{{ layer.name }}</strong><p>{{ layer.detail }}</p></div><span class="layer-code">{{ layer.code }}</span></li></ol>
        </section>
        <section class="recent" aria-labelledby="recent-title"><div class="section-head"><div><span class="section-label">历史任务</span><h2 id="recent-title">最近分析</h2></div><router-link to="/tasks" class="all-link">全部任务 <span aria-hidden="true">→</span></router-link></div>
          <p v-if="historyError" class="history-empty">历史记录暂时无法读取。</p><p v-else-if="history === null" class="history-empty" role="status">正在读取历史记录…</p><p v-else-if="!history.length" class="history-empty">导入首份抓包后，任务会出现在这里。</p>
          <ul v-else class="history-list"><li v-for="item in history" :key="item.id"><router-link :to="{ name: 'task', params: { id: item.id } }"><span class="file-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="file-info"><strong class="truncate" :title="item.name">{{ item.name }}</strong><time :datetime="item.created_at">{{ localDate(item.created_at) }}</time></span><span class="badge" :class="status[item.status]?.[1]">{{ status[item.status]?.[0] || item.status }}</span><span class="row-arrow" aria-hidden="true">↗</span></router-link></li></ul>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.capture-home { max-width:1500px; margin:auto; padding:28px 28px 64px; }
.hero { min-height:370px; position:relative; overflow:hidden; display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,.95fr); background:color-mix(in srgb,var(--surface) 84%,transparent); border:1px solid var(--line-2); border-radius:14px; color:var(--text); backdrop-filter:blur(20px); box-shadow:var(--shadow); }
.hero::after { content:''; position:absolute; inset:0; pointer-events:none; background:repeating-linear-gradient(90deg,transparent 0 95px,var(--grid-line) 96px); }
.hero-copy { z-index:1; padding:48px clamp(30px,5vw,76px); }
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
.exchange { position:relative; z-index:1; padding:24px clamp(18px,3vw,46px); color:var(--text); background:radial-gradient(var(--line-2) 1px,transparent 1px) 0 0/15px 15px; border-inline-start:1px solid var(--line); }
.exchange header,.endpoints { display:flex; align-items:center; justify-content:space-between; }
.exchange header h2 { font-size:18px; }
.exchange header span,.exchange p { color:var(--text-2); font-size:12px; }
.endpoints { margin:20px 0 0; padding:0 5%; }
.endpoints strong { font-size:13px; padding:4px 12px; border:1px solid var(--line-2); border-radius:20px; background:var(--surface); }
.lanes { margin:0 calc(5% + 25px); border-inline:1px dashed var(--line-strong); padding:5px 0; }
.lanes button { width:100%; height:36px; display:grid; place-items:center; position:relative; background:transparent; color:var(--text-3); border:0; cursor:pointer; }
.wire { position:absolute; inset-inline:0; top:50%; height:1px; background:currentColor; }
.wire::after { content:''; position:absolute; right:0; top:-3px; width:6px; height:6px; border-top:1px solid; border-right:1px solid; transform:rotate(45deg); }
.reverse .wire { transform:scaleX(-1); }
.lanes b { position:relative; padding:3px 9px; border-radius:4px; font:600 12px var(--font-mono); background:var(--surface); }
.lanes .chosen { color:var(--brand-lt); }
.chosen .wire::before { content:''; position:absolute; width:5px; height:5px; top:-2px; border-radius:50%; background:currentColor; animation:packet .85s ease-out forwards; }
@keyframes packet { from { left:0 } to { left:calc(100% - 5px) } }
.exchange p { min-height:3em; margin:14px 0 0; }
@media(prefers-reduced-motion:reduce) { .chosen .wire::before { animation:none; } }
.workspace-body { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:28px; margin-top:29px; }.layers,.recent { min-width:0; }.section-head { display:flex; justify-content:space-between; align-items:end; gap:12px; padding-bottom:15px; border-bottom:1px solid var(--line-2); }.section-label { display:block; color:var(--brand-lt); font-size:11px; font-weight:650; margin-bottom:5px; }.section-head h2 { font-size:19px; letter-spacing:-.02em; }.section-hint,.all-link { font-size:12px; color:var(--text-3); }.all-link { color:var(--brand-lt); font-weight:650; text-decoration:none; }.all-link:hover { text-decoration:underline; }
.layer-list,.history-list { list-style:none; }.layer-list li { display:grid; grid-template-columns:38px minmax(0,1fr) auto; gap:10px; align-items:center; padding:15px 0; border-bottom:1px solid var(--line); }.layer-index { color:var(--brand-lt); font:12px var(--font-mono); }.layer-list strong { font-size:13px; }.layer-list p { color:var(--text-3); font-size:11.5px; margin-top:2px; }.layer-code { font:11px var(--font-mono); color:var(--text-3); }
.history-list a { display:flex; align-items:center; gap:12px; min-height:64px; border-bottom:1px solid var(--line); color:var(--text); text-decoration:none; }.history-list a:hover { background:var(--surface-2); }.file-icon { width:34px; height:34px; display:grid; place-items:center; flex:none; color:var(--brand-lt); background:var(--brand-soft); border-radius:7px; }.file-icon svg { width:20px; height:20px; }.file-info { display:grid; gap:3px; min-width:0; flex:1; }.file-info strong { font-size:12.5px; }.file-info time,.history-empty { font-size:11px; color:var(--text-3); }.history-empty { padding:24px 0; }.row-arrow { color:var(--text-4); }
@media (max-width:850px) { .capture-home { padding:20px 16px 48px; }.hero { grid-template-columns:1fr; }.hero-copy { padding:36px 28px; }.exchange { border-inline-start:0; border-top:1px solid var(--line); }.workspace-body { grid-template-columns:1fr; gap:30px; } }
@media (max-width:480px) { .hero-copy { padding:32px 22px; }.hero h1 { font-size:clamp(26px,7.5vw,34px); text-wrap:balance; }.layer-code { font-size:10px; } }
@media (prefers-reduced-motion:reduce) { .upload-button,.sample-button { transition:none; }.upload-button:hover:not(:disabled) { transform:none; } }
</style>
