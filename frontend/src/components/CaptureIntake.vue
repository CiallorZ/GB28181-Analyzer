<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

defineProps({
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
  if (event.dataTransfer.files[0]) emit('file', event.dataTransfer.files[0])
}
</script>

<template>
  <div class="capture-home">
    <header class="home-head">
      <h1>抓包工作台</h1>
      <p>从 SIP 点播到视频画面，追踪每一层的协议证据。</p>
    </header>

    <div class="home-grid">
      <section class="intake-card" aria-labelledby="import-title">
        <div class="panel-heading">
          <h2 id="import-title">导入抓包</h2>
          <span class="local"><i></i>本地解析</span>
        </div>
        <input ref="picker" type="file" accept=".pcap,.pcapng,.cap" hidden @change="pick" />
        <button class="drop-zone" type="button" :class="{ dragging }" :disabled="busy"
                @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false"
                @drop.prevent="drop" @click="picker.click()">
          <span aria-hidden="true" class="upload-glyph">↑</span>
          <template v-if="busy">
            <strong>正在导入 · {{ progress }}%</strong>
            <progress :value="progress" max="100" aria-label="抓包导入进度"></progress>
          </template>
          <template v-else>
            <strong>{{ dragging ? '松开以开始分析' : '拖放抓包文件到这里' }}</strong>
            <small class="mono">.pcap / .pcapng / .cap</small>
            <span class="choose">选择文件</span>
          </template>
        </button>
        <div class="intake-foot">
          <button type="button" class="text-action" :disabled="busy" @click="emit('sample')">
            试用示例抓包 <span aria-hidden="true">↗</span>
          </button>
          <span>合成 SIP + RTP 数据</span>
        </div>
        <div v-if="error" class="err-box import-error" role="alert">{{ error }}</div>
      </section>

      <section class="layers-card" aria-labelledby="layers-title">
        <h2 id="layers-title">分析链路</h2>
        <ol>
          <li v-for="layer in layers" :key="layer.code">
            <div class="layer-line">
              <strong>{{ layer.name }}</strong>
              <span class="layer-code mono">{{ layer.code }}</span>
            </div>
            <p>{{ layer.detail }}</p>
          </li>
        </ol>
      </section>
    </div>

    <section class="recent-card" aria-labelledby="recent-title">
      <div class="panel-heading">
        <h2 id="recent-title">最近分析</h2>
        <router-link to="/tasks" class="text-action">全部任务 <span aria-hidden="true">→</span></router-link>
      </div>
      <p v-if="historyError" class="history-empty">历史记录暂时无法读取。</p>
      <p v-else-if="history === null" class="history-empty" role="status">正在读取历史记录…</p>
      <p v-else-if="!history.length" class="history-empty">导入首份抓包后，任务会出现在这里。</p>
      <ul v-else class="history-list">
        <li v-for="item in history" :key="item.id">
          <router-link :to="{ name: 'task', params: { id: item.id } }">
            <span class="truncate" :title="item.name">{{ item.name }}</span>
            <time :datetime="item.created_at">{{ localDate(item.created_at) }}</time>
            <span class="badge" :class="status[item.status]?.[1]">{{ status[item.status]?.[0] || item.status }}</span>
          </router-link>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.capture-home { width: min(100% - 72px, 1216px); margin: 0 auto; padding: clamp(34px, 6vw, 78px) 0 56px; }
.home-head { margin-bottom: 30px; }
.home-head h1 { font-size: clamp(32px, 4vw, 50px); font-weight: 720; letter-spacing: -.055em; line-height: 1.12; }
.home-head p { margin-top: 12px; color: var(--text-2); font-size: 15px; }
.home-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(290px, 1fr); gap: 16px; }
.intake-card, .layers-card, .recent-card { border: 1px solid var(--line); border-radius: 14px; background: var(--surface); padding: 22px; }
.panel-heading, .intake-foot, .layer-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 16px; font-weight: 700; }
.local { display: flex; align-items: center; gap: 7px; color: var(--text-3); font-size: 12px; }
.local i { width: 6px; height: 6px; background: var(--ok); border-radius: 50%; }
.drop-zone {
  width: 100%; min-height: 204px; margin: 16px 0 13px; display: grid; justify-items: center;
  align-content: center; gap: 5px; padding: 19px; border: 1px dashed var(--line-strong);
  border-radius: 10px; cursor: pointer; color: var(--text); font: inherit;
  background: var(--surface-2);
  transition: background-color var(--dur), border-color var(--dur);
}
.drop-zone:hover:not(:disabled), .drop-zone.dragging { background: var(--brand-soft); border-color: var(--brand); }
.drop-zone:disabled { cursor: progress; }
.upload-glyph {
  display: grid; place-items: center; width: 37px; height: 37px; margin-bottom: 5px;
  background: var(--surface); border: 1px solid var(--line-2); border-radius: 8px;
  font-size: 22px; line-height: 1; transition: transform var(--dur) var(--ease);
}
.drop-zone:hover:not(:disabled) .upload-glyph, .drop-zone.dragging .upload-glyph { transform: translateY(-3px); }
.drop-zone small, .intake-foot > span, .layer-line + p, .history-empty, time { color: var(--text-3); font-size: 12px; }
.choose {
  margin-top: 7px; padding: 5px 15px; border-radius: 6px; font-size: 12px; font-weight: 650;
  color: var(--ink-btn-text); background: var(--ink-btn);
}
progress { width: min(100%, 220px); accent-color: var(--brand); }
.text-action { color: var(--text); font: inherit; font-size: 12px; font-weight: 650; text-align: left; }
button.text-action { background: none; border: 0; cursor: pointer; padding: 3px 0; }
.text-action:disabled { opacity: .65; cursor: default; }
.text-action:hover { text-decoration: underline; text-underline-offset: 4px; }
.import-error { margin-top: 14px; }
.layers-card { background: var(--surface-2); }
.layers-card ol { list-style: none; margin-top: 20px; padding-left: 22px; }
.layers-card li { position: relative; padding: 0 0 24px 15px; border-left: 1px solid var(--line-strong); }
.layers-card li:last-child { border-color: transparent; padding-bottom: 0; }
.layers-card li::before {
  content: ''; position: absolute; inset: 8px auto auto -4px; width: 7px; height: 7px;
  background: var(--surface-2); border: 1px solid var(--brand); border-radius: 2px;
}
.layer-code { color: var(--text-2); font-size: 10px; white-space: nowrap; }
.recent-card { margin-top: 16px; }
.history-empty { margin-top: 14px; }
.history-list { margin-top: 12px; list-style: none; }
.history-list a {
  display: grid; grid-template-columns: minmax(0, 1fr) auto 62px; align-items: center; gap: 18px;
  min-height: 43px; border-top: 1px solid var(--line); padding: 6px 8px; color: var(--text); text-decoration: none;
}
.history-list a:hover { background: var(--surface-2); }
.history-list .badge { justify-self: end; }
@media (max-width: 760px) {
  .capture-home { width: calc(100% - 32px); }
  .home-grid { grid-template-columns: 1fr; }
}
@media (max-width: 430px) {
  .intake-card, .layers-card, .recent-card { padding: 15px; }
  .history-list a { grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
  .history-list time { display: none; }
}
</style>
