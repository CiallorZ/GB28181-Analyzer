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
      <div class="hero-copy">
        <div class="hero-meta"><span class="hero-mark"></span>中国铁塔 · 视联网协议分析</div>
        <h1 id="hero-title">让抓包<br><em>说出问题。</em></h1>
        <p>从 SIP 信令到视频画面，沿着真实证据定位每一个故障环节。</p>
        <div class="hero-actions">
          <input ref="picker" type="file" accept=".pcap,.pcapng,.cap" hidden @change="pick" />
          <button class="upload-button" type="button" :disabled="busy" @click="picker.click()">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {{ busy ? `正在导入 ${progress}%` : '选择抓包文件' }}
          </button>
          <button type="button" class="sample-button" :disabled="busy" @click="emit('sample')">试用示例抓包 <span aria-hidden="true">↗</span></button>
        </div>
        <progress v-if="busy" :value="progress" max="100" aria-label="抓包导入进度"></progress>
        <div class="hero-note">支持 PCAP / PCAPNG / CAP <span></span> 抓包由分析服务所在设备处理</div>
        <div v-if="error" class="hero-error" role="alert">{{ error }}</div>
      </div>
      <div class="hero-art" :class="{ active: busy }" aria-hidden="true">
        <svg viewBox="0 0 590 420" fill="none"><defs><linearGradient id="beam" x1="0" y1="0" x2="1" y2="1"><stop stop-color="var(--brand-lt)" stop-opacity=".52"/><stop offset="1" stop-color="var(--brand-lt)" stop-opacity=".06"/></linearGradient></defs>
          <circle cx="325" cy="210" r="166" stroke="var(--brand-lt)" stroke-opacity=".12"/><circle cx="325" cy="210" r="126" stroke="var(--brand-lt)" stroke-opacity=".18"/><circle cx="325" cy="210" r="86" stroke="var(--brand-lt)" stroke-opacity=".25"/>
          <path d="M0 210H590M325 0V420M208 92l234 236M208 328 442 92" stroke="var(--brand-lt)" stroke-opacity=".12"/>
          <path class="route-trace" d="M92 303H194L247 248H308L352 184H418L461 122H550" stroke="url(#beam)" stroke-width="2"/>
          <g fill="var(--brand-lt)"><circle cx="92" cy="303" r="4"/><circle cx="247" cy="248" r="4"/><circle cx="352" cy="184" r="4"/><circle cx="461" cy="122" r="4"/></g>
          <path d="M325 135l-35 150h70l-35-150Zm-22 91h44m-53 45h62m-44-73 27 0" stroke="var(--brand-lt)" stroke-opacity=".75" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M303 150c-25 11-42 34-42 60m86-60c25 11 42 34 42 60M286 133c-33 16-56 44-56 77m134-77c33 16 56 44 56 77" stroke="var(--brand-lt)" stroke-opacity=".34" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span>信令</span><span>协商</span><span>媒体</span><span>画面</span>
      </div>
    </section>
    <section class="workspace" aria-label="分析入口与历史任务">
      <div class="drop-panel" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
        <div class="drop-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4m-4 4 4-4 4 4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><strong>{{ dragging ? '松开以导入抓包' : '拖放抓包文件到这里' }}</strong><p>也可以使用上方按钮选择文件</p></div>
        <span class="drop-format">.pcap / .pcapng / .cap</span>
      </div>
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
.hero h1 em { font-style:normal; color:var(--text); }
.hero-copy > p { color:var(--text-2); font-size:14px; line-height:1.8; max-width:440px; }
.hero-actions { display:flex; gap:12px; align-items:center; margin-top:27px; flex-wrap:wrap; }
.upload-button,.sample-button { min-height:42px; border-radius:5px; padding:0 17px; font:inherit; font-size:13px; font-weight:650; cursor:pointer; display:inline-flex; gap:9px; align-items:center; justify-content:center; transition:transform .18s,background .18s; }
.upload-button { background:var(--brand-dk); color:#fff; border:1px solid var(--brand-dk); }.upload-button svg { width:17px; height:17px; }.upload-button:hover:not(:disabled) { background:var(--brand); transform:translateY(-2px); }
.sample-button { background:var(--surface); color:var(--text); border:1px solid var(--line-2); }.sample-button:hover:not(:disabled) { background:var(--surface-3); }.sample-button span { margin-left:4px; }
.upload-button:disabled,.sample-button:disabled { opacity:.7; cursor:progress; }.hero progress { display:block; width:220px; max-width:100%; margin-top:14px; accent-color:var(--brand); }
.hero-note { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:19px; color:var(--text-3); font-size:11px; }.hero-note span { width:3px; height:3px; border-radius:50%; background:currentColor; }.hero-error { margin-top:12px; font-size:12px; color:var(--critical); font-weight:600; }
.hero-art { position:relative; z-index:1; display:flex; align-items:center; justify-content:center; min-width:0; }.hero-art svg { width:100%; max-width:590px; }.hero-art > span { position:absolute; bottom:13%; color:var(--text-3); font-size:11px; }.hero-art > span:nth-of-type(1) { left:16%; }.hero-art > span:nth-of-type(2) { left:35%; }.hero-art > span:nth-of-type(3) { left:55%; }.hero-art > span:nth-of-type(4) { left:76%; }
.hero-art.active .route-trace { stroke-dasharray:10 10; animation: trace-flow 1s linear infinite; }
@keyframes trace-flow { to { stroke-dashoffset:-20; } }
.workspace { padding:22px 0 0; }.drop-panel { display:flex; align-items:center; gap:15px; min-height:96px; padding:18px 22px; border:1px dashed var(--line-strong); border-radius:8px; background:var(--surface); transition:border-color .2s,background .2s; }.drop-panel.dragging { border-color:var(--brand); background:var(--brand-soft); }.drop-icon { width:42px; height:42px; display:grid; place-items:center; flex:none; border-radius:9px; background:var(--brand-soft); color:var(--brand-lt); }.drop-icon svg { width:22px; height:22px; }.drop-panel strong { font-size:13px; }.drop-panel p { font-size:12px; color:var(--text-3); margin-top:2px; }.drop-format { margin-left:auto; font:11px var(--font-mono); color:var(--text-3); }
.workspace-body { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:28px; margin-top:29px; }.layers,.recent { min-width:0; }.section-head { display:flex; justify-content:space-between; align-items:end; gap:12px; padding-bottom:15px; border-bottom:1px solid var(--line-2); }.section-label { display:block; color:var(--brand-lt); font-size:11px; font-weight:650; margin-bottom:5px; }.section-head h2 { font-size:19px; letter-spacing:-.02em; }.section-hint,.all-link { font-size:12px; color:var(--text-3); }.all-link { color:var(--brand-lt); font-weight:650; text-decoration:none; }.all-link:hover { text-decoration:underline; }
.layer-list,.history-list { list-style:none; }.layer-list li { display:grid; grid-template-columns:38px minmax(0,1fr) auto; gap:10px; align-items:center; padding:15px 0; border-bottom:1px solid var(--line); }.layer-index { color:var(--brand-lt); font:12px var(--font-mono); }.layer-list strong { font-size:13px; }.layer-list p { color:var(--text-3); font-size:11.5px; margin-top:2px; }.layer-code { font:11px var(--font-mono); color:var(--text-3); }
.history-list a { display:flex; align-items:center; gap:12px; min-height:64px; border-bottom:1px solid var(--line); color:var(--text); text-decoration:none; }.history-list a:hover { background:var(--surface-2); }.file-icon { width:34px; height:34px; display:grid; place-items:center; flex:none; color:var(--brand-lt); background:var(--brand-soft); border-radius:7px; }.file-icon svg { width:20px; height:20px; }.file-info { display:grid; gap:3px; min-width:0; flex:1; }.file-info strong { font-size:12.5px; }.file-info time,.history-empty { font-size:11px; color:var(--text-3); }.history-empty { padding:24px 0; }.row-arrow { color:var(--text-4); }
@media (max-width:850px) { .capture-home { padding:20px 16px 48px; }.hero { grid-template-columns:1fr; }.hero-copy { padding:36px 28px; }.hero-art { position:absolute; right:-60px; top:0; width:55%; height:100%; opacity:.42; pointer-events:none; }.hero-art > span { display:none; }.workspace-body { grid-template-columns:1fr; gap:30px; } }
@media (max-width:480px) { .hero-copy { padding:32px 22px; }.hero h1 { font-size:40px; }.hero-art { width:70%; right:-90px; }.drop-format { display:none; }.drop-panel { padding:15px; }.layer-code { font-size:10px; } }
@media (prefers-reduced-motion:reduce) { .upload-button,.sample-button,.drop-panel { transition:none; }.upload-button:hover:not(:disabled) { transform:none; }.hero-art.active .route-trace { animation:none; stroke-dasharray:none; } }
</style>
