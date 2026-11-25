<script setup>
import InterfacePreferences from '../components/InterfacePreferences.vue'
import { ref, onMounted } from 'vue'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'

const health = ref(null)
const rules = ref([])
const err = ref('')
const tools = ref(null)
const toolDraft = ref({ tshark: '', capinfos: '', ffmpeg: '', ffprobe: '', dumpcap: '' })
const toolBusy = ref(false)
const toolMsg = ref('')
const toolErr = ref('')
const toolItems = [
  { key: 'tshark', label: 'TShark' },
  { key: 'capinfos', label: 'Capinfos' },
  { key: 'dumpcap', label: 'Dumpcap' },
  { key: 'ffmpeg', label: 'FFmpeg' },
  { key: 'ffprobe', label: 'FFprobe' }
]

function sourceLabel(source) {
  return { manual: '手动', environment: '环境/内置', path: 'PATH', auto: '自动探测', missing: '缺失' }[source] || source
}

function sourceClass(source) {
  return { manual: 'ok', environment: 'info', path: 'info', auto: 'unknown', missing: 'critical' }[source]
}

function syncDraft() {
  for (const item of toolItems) {
    toolDraft.value[item.key] = tools.value?.tools?.[item.key]?.configured || ''
  }
}

async function loadTools() {
  tools.value = await api.tools()
  syncDraft()
}

async function refreshHealth() {
  health.value = await api.health()
}

async function saveTools() {
  toolBusy.value = true
  toolErr.value = ''
  toolMsg.value = ''
  try {
    tools.value = await api.saveTools(toolDraft.value)
    syncDraft()
    await refreshHealth()
    toolMsg.value = '工具路径已保存，新分析立即使用'
  } catch (e) {
    toolErr.value = e.message
  } finally {
    toolBusy.value = false
  }
}

async function resetTools() {
  toolBusy.value = true
  toolErr.value = ''
  toolMsg.value = ''
  try {
    tools.value = await api.resetTools()
    syncDraft()
    await refreshHealth()
    toolMsg.value = '已恢复自动探测'
  } catch (e) {
    toolErr.value = e.message
  } finally {
    toolBusy.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([refreshHealth(), loadTools()])
    const r = await api.rules()
    rules.value = r.rules || []
  } catch (e) { err.value = e.message }
})
</script>

<template>
  <div class="page">
    <PageNav
      title="系统设置"
      sub="运行环境与诊断规则说明"
      :crumbs="[{label:'工作台', to:'/'}, {label:'系统设置'}]" />

    <InterfacePreferences />
    <div v-if="err" class="err-box">{{ err }}</div>

    <div class="card mb-16">
      <div class="card-head">运行环境</div>
      <div class="card-body">
        <div class="kv-grid" v-if="health">
          <div><span>服务状态</span><b class="text-ok">运行中</b></div>
          <div><span>版本</span><b>{{ health.version }}</b></div>
          <div><span>数据库</span><b>{{ health.database }}</b></div>
          <div>
            <span>tshark</span>
            <b :class="health.dependencies?.tshark ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.tshark ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>ffmpeg</span>
            <b :class="health.dependencies?.ffmpeg ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.ffmpeg ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>ffprobe</span>
            <b :class="health.dependencies?.ffprobe ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.ffprobe ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>capinfos</span>
            <b :class="health.dependencies?.capinfos ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.capinfos ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>dumpcap</span>
            <b :class="health.dependencies?.dumpcap ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.dumpcap ? '可用' : '缺失' }}
            </b>
          </div>
          <div class="full"><span>tshark 路径</span><b class="mono-sm">{{ health.tshark_path || '—' }}</b></div>
          <div class="full"><span>ffmpeg 路径</span><b class="mono-sm">{{ health.ffmpeg_path || '—' }}</b></div>
          <div class="full"><span>运行日志</span><b class="mono-sm">{{ health.log_path || '—' }}</b></div>
        </div>
      </div>
    </div>

    <div class="card mb-16">
      <div class="card-head">
        外部工具路径
        <span class="count-badge">修改后立即生效</span>
      </div>
      <div class="card-body">
        <p class="tool-help">
          优先级：手动配置 &gt; 环境变量 &gt; PATH / 打包内置。留空表示继续使用自动探测。
          离线包已内置工具，手动路径可用于替换成本机指定版本。
        </p>
        <div class="tool-grid" v-if="tools">
          <label v-for="item in toolItems" :key="item.key" class="tool-field">
            <span>{{ item.label }}</span>
            <div class="tool-line">
              <input
                v-model="toolDraft[item.key]"
                class="inp mono"
                :placeholder="tools.tools[item.key]?.path || '未检测到'"
                spellcheck="false"
              />
              <span class="badge" :class="sourceClass(tools.tools[item.key]?.source)">
                {{ sourceLabel(tools.tools[item.key]?.source) }}
              </span>
            </div>
            <small v-if="tools.tools[item.key]?.path" class="mono-sm">
              {{ tools.tools[item.key].path }}
            </small>
            <small v-if="tools.tools[item.key]?.configured_missing" class="tool-warn">
              手动路径不可用，当前已回退到自动探测。请修正或清空。
            </small>
          </label>
        </div>
        <p v-if="toolErr" class="tool-error">{{ toolErr }}</p>
        <p v-if="toolMsg" class="tool-ok">{{ toolMsg }}</p>
        <div class="tool-actions">
          <button class="btn sm" :disabled="toolBusy" @click="saveTools">
            {{ toolBusy ? '保存中…' : '保存路径' }}
          </button>
          <button class="btn sm secondary" :disabled="toolBusy" @click="resetTools">
            恢复自动探测
          </button>
        </div>
      </div>
    </div>

    <div class="card mb-16">
      <div class="card-head">
        诊断规则清单
        <span class="count-badge">
          {{ rules.filter(r => r.implemented).length }} / {{ rules.length }} 已接入
        </span>
      </div>
      <div class="card-body tight">
        <table class="tbl">
          <thead><tr><th>规则 ID</th><th>名称</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="r in rules" :key="r.id">
              <td class="mono text-dim">{{ r.id }}</td>
              <td>{{ r.name }}</td>
              <td>
                <span class="badge" :class="r.implemented ? 'ok' : 'unknown'">
                  {{ r.implemented ? '已接入' : '规划中' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-head">分析局限说明</div>
      <div class="card-body">
        <div class="limits">
          <div class="limit-item">
            <b>分析结果仅反映抓包点观察到的流量</b>
            <p>本平台的所有指标均由上传的抓包文件计算得出。抓包点之外的网络状况、
              客户端实际播放效果，无法从单点抓包推断。</p>
          </div>
          <div class="limit-item">
            <b>SIP 成功 ≠ 媒体成功 ≠ 播放成功</b>
            <p>SIP 200 OK 只代表信令层同意建立会话。媒体是否真正传输、
              能否解码、播放器是否显示画面，是三个独立层面，本平台分别标注。</p>
          </div>
          <div class="limit-item">
            <b>RTP 序号缺口 ≠ 网络丢包</b>
            <p>序号缺口可能来自真实丢包、抓包缓冲区溢出、或抓包点位于会话中途。
              TCP 承载时尤其不能直接判定为丢包，平台会标注证据等级。</p>
          </div>
          <div class="limit-item">
            <b>无法计算的指标不显示为 0</b>
            <p>缺少起止事件时，指标显示为「无法计算」或「—」，
              以免把「没有数据」误解为「数据为 0」。</p>
          </div>
          <div class="limit-item">
            <b>RTP 首包 ≠ 视频首帧</b>
            <p>首个 RTP 包到达不代表画面已可显示。视频首帧需要解码关键帧，
              当前帧结构统计与视频重建不能证明客户端已显示首帧。</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.h1 { font-size: 20px; font-weight: 600; }
.sub { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.kv-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 26px;
  border-top: 1px solid var(--line);
}
.kv-grid > div {
  display: flex; flex-direction: column; gap: 3px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.kv-grid > div.full { grid-column: 1 / -1; }
.kv-grid span { color: var(--text-4); width: auto; font-size: 11.5px; }
.kv-grid b { color: var(--text); font-weight: 500; font-size: 13px; font-family: var(--font-mono); word-break: break-all; }
@media (max-width: 860px) { .kv-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .kv-grid { grid-template-columns: 1fr; } }
.tool-help {
  font-size: 12.5px; color: var(--text-3); line-height: 1.75; margin-bottom: 14px;
}
.tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; }
.tool-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.tool-field > span { font-size: 11.5px; color: var(--text-4); }
.tool-line { display: flex; align-items: center; gap: 8px; }
.tool-line .inp { flex: 1; min-width: 0; }
.tool-field small { color: var(--text-3); overflow-wrap: anywhere; }
.tool-warn { color: var(--warning) !important; }
.tool-actions { display: flex; gap: 8px; margin-top: 14px; }
.tool-error { color: var(--critical); font-size: 12.5px; margin-top: 10px; }
.tool-ok { color: var(--ok); font-size: 12.5px; margin-top: 10px; }
.btn.secondary { background: var(--surface-2); color: var(--text-2); border-color: var(--line-2); }
@media (max-width: 760px) { .tool-grid { grid-template-columns: 1fr; } }
.count-badge {
  font-size: 11px; padding: 1px 7px; border-radius: 99px;
  background: var(--panel-3); color: var(--text-3);
}
.limits { display: flex; flex-direction: column; gap: 16px; }
.limit-item {
  padding-left: 12px; border-left: 2px solid var(--border-2);
}
.limit-item b {
  display: block; font-size: 13px; color: var(--text);
  font-weight: 600; margin-bottom: 5px;
}
.limit-item p {
  font-size: 12.5px; color: var(--text-3); line-height: 1.75;
}
.err-box {
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 12px 14px; font-size: 13px;
  color: var(--critical); margin-bottom: 14px;
}
</style>
