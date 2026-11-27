<script setup>
import InterfacePreferences from '../components/InterfacePreferences.vue'
import { inject, ref, computed, nextTick, onMounted } from 'vue'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'

const health = ref(null)
const rules = ref([])
const err = ref('')
const activeTab = ref('interface')
const { appearance, chooseAppearance } = inject('workspaceAppearance')
const tabs = [
  { key: 'interface', label: '界面与反馈' },
  { key: 'dependencies', label: '运行依赖' },
  { key: 'rules', label: '规则与边界' }
]
const tools = ref(null)
const toolDraft = ref({ tshark: '', capinfos: '', ffmpeg: '', ffprobe: '', dumpcap: '' })
const toolBusy = ref(false)
const toolMsg = ref('')
const toolErr = ref('')
const toolProbe = ref({})
const probeBusy = ref('')
const toolGroups = [
  {
    title: 'Wireshark / TShark',
    detail: '抓包读取、概要统计与实时采集',
    items: [
      { key: 'tshark', label: 'TShark' },
      { key: 'capinfos', label: 'Capinfos' },
      { key: 'dumpcap', label: 'Dumpcap' }
    ]
  },
  {
    title: 'FFmpeg',
    detail: '编码探测与视频预览',
    items: [
      { key: 'ffmpeg', label: 'FFmpeg' },
      { key: 'ffprobe', label: 'FFprobe' }
    ]
  }
]
const toolItems = toolGroups.flatMap(group => group.items)

const depDefs = [
  { key: 'tshark', label: 'TShark', role: '信令与报文解析' },
  { key: 'capinfos', label: 'Capinfos', role: '抓包概要统计' },
  { key: 'dumpcap', label: 'Dumpcap', role: '本机网卡实时采集' },
  { key: 'ffmpeg', label: 'FFmpeg', role: '视频重建与转码' },
  { key: 'ffprobe', label: 'FFprobe', role: '编码参数探测' }
]
const dependencies = computed(() => depDefs.map(dep => ({
  ...dep,
  ok: Boolean(health.value?.dependencies?.[dep.key])
})))
const missingDeps = computed(() => dependencies.value.filter(dep => !dep.ok))

/* 标签页遵循 tablist 键盘约定：左右键循环，Home/End 跳到首尾。 */
function onTabKey(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const index = tabs.findIndex(tab => tab.key === activeTab.value)
  let next = index
  if (['ArrowLeft', 'ArrowUp'].includes(event.key)) next = (index - 1 + tabs.length) % tabs.length
  if (['ArrowRight', 'ArrowDown'].includes(event.key)) next = (index + 1) % tabs.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = tabs.length - 1
  activeTab.value = tabs[next].key
  nextTick(() => document.getElementById('settings-tab-' + tabs[next].key)?.focus())
}

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

function clearProbe(key) {
  if (toolProbe.value[key]) {
    toolProbe.value = { ...toolProbe.value, [key]: null }
  }
}

async function chooseTool(item) {
  if (!window.nsh) {
    toolErr.value = '当前浏览器无法打开原生文件选择器，请直接输入完整路径'
    return
  }
  toolErr.value = ''
  try {
    const path = await api.pickTool()
    if (path) {
      toolDraft.value[item.key] = path
      await testTool(item)
    }
  } catch (e) {
    toolErr.value = e.message || '无法打开文件选择器'
  }
}

async function testTool(item) {
  const draftValue = toolDraft.value[item.key] || ''
  const path = draftValue.trim() || tools.value?.tools?.[item.key]?.path
  toolErr.value = ''
  if (!path) {
    toolProbe.value = { ...toolProbe.value, [item.key]: { ok: false, error: '没有可测试的路径' } }
    return
  }
  probeBusy.value = item.key
  try {
    const result = await api.probeTool({ name: item.key, path })
    // 探测期间用户改了路径：旧结果已经对不上当前输入，直接丢弃。
    if ((toolDraft.value[item.key] || '') !== draftValue) return
    toolProbe.value = { ...toolProbe.value, [item.key]: result }
  } catch (e) {
    if ((toolDraft.value[item.key] || '') !== draftValue) return
    toolProbe.value = { ...toolProbe.value, [item.key]: { ok: false, error: e.message } }
  } finally {
    if (probeBusy.value === item.key) probeBusy.value = ''
  }
}

const nativeDesktop = Boolean(window.nsh)
const installing = ref(false)
async function installTools() {
  if (!confirm('将通过 WinGet 联网安装缺少的 Wireshark 或 FFmpeg，并接受对应软件包协议。继续安装？')) return
  installing.value = true
  window.nsh?.postMessage?.('install-busy')
  toolMsg.value = toolErr.value = ''
  try {
    tools.value = await api.installTools()
    syncDraft()
    await refreshHealth()
    toolMsg.value = Object.values(tools.value.tools).every(t => t.available) ? '分析工具已全部就绪' : '请检查尚未识别的工具路径'
  } catch (e) {
    toolErr.value = e.response?.data?.detail || e.message
  } finally {
    window.nsh?.postMessage?.('install-idle')
    installing.value = false
  }
}

async function saveTools() {
  toolBusy.value = true
  toolErr.value = ''
  toolMsg.value = ''
  try {
    tools.value = await api.saveTools(toolDraft.value)
    toolProbe.value = {}
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
  if (!confirm('将清空手动工具路径并恢复自动探测，继续吗？')) return
  toolBusy.value = true
  toolErr.value = ''
  toolMsg.value = ''
  try {
    tools.value = await api.resetTools()
    toolProbe.value = {}
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

    <div v-if="err" class="err-box mb-14">{{ err }}</div>

    <div class="settings-layout">
    <nav class="settings-tabs" role="tablist" aria-orientation="vertical" aria-label="设置分区">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :id="'settings-tab-' + tab.key"
        class="settings-tab"
        :class="{ on: activeTab === tab.key }"
        role="tab"
        :aria-selected="activeTab === tab.key"
        :aria-controls="'settings-panel-' + tab.key"
        :tabindex="activeTab === tab.key ? 0 : -1"
        @click="activeTab = tab.key"
        @keydown="onTabKey"
      ><AppIcon :name="{ interface: 'monitor', dependencies: 'codec', rules: 'file' }[tab.key]" />{{ tab.label }}</button>
    </nav>

    <section v-show="activeTab === 'interface'" id="settings-panel-interface"
             v-panel-change="activeTab" role="tabpanel" aria-labelledby="settings-tab-interface" tabindex="0">
      <div class="card card-body mb-16 appearance-setting">
        <label for="settings-appearance">主题模式</label>
        <select id="settings-appearance" class="inp" v-model="appearance" @change="chooseAppearance">
          <option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option>
        </select>
      </div>
      <InterfacePreferences />
    </section>

    <section v-show="activeTab === 'dependencies'" id="settings-panel-dependencies"
             v-panel-change="activeTab" role="tabpanel" aria-labelledby="settings-tab-dependencies" tabindex="0">
    <div class="card mb-16">
      <div class="card-head">运行环境</div>
      <div class="card-body">
        <div class="dep-body" v-if="health">
          <div class="dep-chips">
            <span v-for="dep in dependencies" :key="dep.key"
                  class="dep-chip" :class="{ bad: !dep.ok }" :title="dep.role">
              <i aria-hidden="true"></i>{{ dep.label }}
              <b>{{ dep.ok ? '可用' : '缺失' }}</b>
            </span>
          </div>
          <p class="dep-note" :class="{ warn: missingDeps.length }">
            {{ missingDeps.length
              ? '缺少 ' + missingDeps.map(dep => dep.label).join('、') + '，相关功能受限，可在下方手动指定路径。'
              : '依赖全部就绪：抓包分析、视频预览与实时采集均可用。' }}
          </p>
          <div class="dep-meta">
            <span>服务 <b>运行中</b></span>
            <span>版本 <b>{{ health.version }}</b></span>
            <span>数据库 <b>{{ health.database }}</b></span>
          </div>
          <div class="dep-log">
            <span>运行日志</span>
            <code>{{ health.log_path || '—' }}</code>
          </div>
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
        <div class="tool-groups" v-if="tools">
          <section v-for="group in toolGroups" :key="group.title" class="tool-group">
            <header>
              <strong>{{ group.title }}</strong>
              <small>{{ group.detail }}</small>
            </header>
            <div v-for="item in group.items" :key="item.key" class="tool-row">
              <div class="tool-ident">
                <strong>{{ item.label }}</strong>
                <span class="badge" :class="sourceClass(tools.tools[item.key]?.source)">
                  {{ sourceLabel(tools.tools[item.key]?.source) }}
                </span>
              </div>
              <div class="tool-edit">
                <input
                  v-model="toolDraft[item.key]"
                  class="inp mono"
                  :aria-label="item.label + ' 路径'"
                  placeholder="留空使用自动探测"
                  spellcheck="false"
                  @input="clearProbe(item.key)"
                />
                <button class="btn ghost sm" @click="chooseTool(item)">浏览</button>
                <button
                  class="btn ghost sm"
                  :disabled="probeBusy === item.key"
                  @click="testTool(item)"
                >{{ probeBusy === item.key ? '测试中…' : '测试' }}</button>
              </div>
              <div class="tool-detail">
                <span v-if="tools.tools[item.key]?.path" class="mono-sm">
                  当前生效：{{ tools.tools[item.key].path }}
                </span>
                <span
                  v-if="toolProbe[item.key]"
                  :class="toolProbe[item.key].ok ? 'probe-ok' : 'probe-error'"
                >{{ toolProbe[item.key].ok
                    ? '可用 · ' + (toolProbe[item.key].version || '版本未返回')
                    : '不可用 · ' + toolProbe[item.key].error }}</span>
                <span v-if="tools.tools[item.key]?.configured_missing" class="tool-warn">
                  手动路径不可用，当前已回退到自动探测。请修正或清空。
                </span>
                <span v-if="item.key === 'dumpcap' && !tools.tools[item.key]?.available" class="tool-warn">
                  实时网卡采集需要 Dumpcap 与 Npcap；抓包文件分析不受影响。
                </span>
              </div>
            </div>
          </section>
        </div>
        <p v-if="toolErr" class="tool-error">{{ toolErr }}</p>
        <p v-if="toolMsg" class="tool-ok">{{ toolMsg }}</p>
        <div class="tool-actions">
          <button v-if="nativeDesktop" class="btn primary sm" :disabled="installing || toolBusy" @click="installTools">
            {{ installing ? '正在安装依赖…' : '一键安装缺失依赖' }}
          </button>
          <button class="btn primary sm" :disabled="toolBusy || installing" @click="saveTools">
            {{ toolBusy ? '保存中…' : '保存路径' }}
          </button>
          <button class="btn ghost sm" :disabled="toolBusy || installing" @click="resetTools">
            恢复自动探测
          </button>
          <span class="tool-actions-note">建议先点“测试”，确认工具版本后再保存。</span>
        </div>
      </div>
    </div>
    </section>

    <section v-show="activeTab === 'rules'" id="settings-panel-rules"
             v-panel-change="activeTab" role="tabpanel" aria-labelledby="settings-tab-rules" tabindex="0">
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
    </section>
    </div>
  </div>
</template>

<style scoped>
.dep-body { display: flex; flex-direction: column; gap: 11px; }
.dep-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.dep-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px 4px 9px; border-radius: 99px;
  border: 1px solid var(--line-2); background: var(--surface-2);
  font-size: 11.5px; color: var(--text-2);
}
.dep-chip i { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); flex: none; }
.dep-chip b { font-weight: 550; color: var(--ok); }
.dep-chip.bad { border-color: var(--critical); }
.dep-chip.bad i { background: var(--critical); }
.dep-chip.bad b { color: var(--critical); }
.dep-note { font-size: 11.5px; color: var(--text-4); line-height: 1.6; }
.dep-note.warn { color: var(--warning); }
.dep-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 11.5px; color: var(--text-4); }
.dep-meta b { color: var(--text-2); font-weight: 500; font-family: var(--font-mono); }
.dep-log { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; font-size: 11.5px; color: var(--text-4); }
.dep-log code { font-family: var(--font-mono); color: var(--text-3); overflow-wrap: anywhere; }
.settings-tabs {
  display: flex; gap: 4px; margin-bottom: 16px;
  border-bottom: 1px solid var(--line);
  overflow-x: auto; scrollbar-width: none;
}
.settings-tab {
  flex: none; height: 38px; padding: 0 14px;
  border: 0; border-bottom: 2px solid transparent;
  background: transparent; color: var(--text-3);
  font: inherit; font-size: 12.5px; cursor: pointer;
}
.settings-tab:hover { color: var(--text); }
.settings-tab.on { color: var(--text); font-weight: 650; border-bottom-color: var(--brand); }
.tool-help {
  font-size: 12.5px; color: var(--text-3); line-height: 1.75; margin-bottom: 14px;
}
.tool-groups { display: flex; flex-direction: column; gap: 18px; }
.tool-group { border-top: 1px solid var(--line); padding-top: 14px; }
.tool-group header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.tool-group header strong { font-size: 13px; }
.tool-group header small { color: var(--text-4); font-size: 11.5px; }
.tool-row {
  display: grid; grid-template-columns: 150px minmax(0, 1fr);
  gap: 8px 18px; padding: 10px 0; border-bottom: 1px solid var(--line);
  min-width: 0;
}
.tool-row:last-child { border-bottom: 0; }
.tool-ident { display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }
.tool-ident strong { font-size: 12.5px; }
.tool-edit { display: flex; gap: 8px; min-width: 0; }
.tool-edit .inp { flex: 1; min-width: 0; }
.tool-detail { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px 14px; }
.tool-detail span {
  color: var(--text-3); font-size: 11.5px;
  overflow-wrap: anywhere; word-break: break-word;
}
.probe-ok { color: var(--ok) !important; }
.probe-error { color: var(--critical) !important; }
.tool-warn { color: var(--warning) !important; }
.tool-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; }
.tool-actions-note { color: var(--text-4); font-size: 11.5px; }
@media (max-width: 430px) {
  .tool-edit .btn { padding: 0 8px; }
  .tool-detail span { font-size: 11px; }
}
.tool-row .badge { white-space: nowrap; }
.tool-error { color: var(--critical); font-size: 12.5px; margin-top: 10px; }
.tool-ok { color: var(--ok); font-size: 12.5px; margin-top: 10px; }
@media (max-width: 680px) {
  .tool-row { grid-template-columns: 1fr; }
  .tool-edit { flex-wrap: wrap; }
  .tool-edit .btn { flex: 0 0 auto; }
}
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
.settings-layout { display:grid; grid-template-columns:155px minmax(0,1fr); gap:var(--space-4); align-items:start; }
.settings-tabs { flex-direction:column; border:1px solid var(--line); padding:var(--space-1); border-radius:var(--radius); background:var(--surface); }
.settings-tab { text-align:left; border:0; border-inline-start:3px solid transparent; border-radius:var(--radius-xs); }
.settings-tab.on { color:var(--brand-lt); background:var(--bg-selected); border-color:var(--brand); }
@media (max-width:720px) { .settings-layout { grid-template-columns:minmax(0,1fr); } }
.appearance-setting { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.settings-tab { display:flex; align-items:center; gap:9px; min-height:38px; }.settings-tab svg { width:15px; }
</style>
