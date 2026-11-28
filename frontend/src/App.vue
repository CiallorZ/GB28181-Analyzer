<script setup>
import { ref, onMounted, onUnmounted, computed, watch, provide, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api/client'
import { useTaskStore } from './stores/task'

const AiPanel = defineAsyncComponent(() => import('./components/AiPanel.vue'))
const store = useTaskStore()
const route = useRoute()
const aiPanelMounted = ref(store.aiPanelOpen)
watch(() => store.aiPanelOpen, (open) => {
  // 首次打开才下载会诊面板；之后保留组件，关闭抽屉不丢失报告和追问。
  if (open) aiPanelMounted.value = true
}, { immediate: true })
const aiFocusByPage = { sip: 'sip', media: 'media', packets: 'packet', diagnostics: 'field', insight: 'general', 'session-detail': 'sip' }
function openPageConsultation() {
  store.openAiPanel(aiFocusByPage[route.name] || 'general')
}

const savedAppearance = document.documentElement.dataset.appearance
const appearance = ref(['light', 'dark'].includes(savedAppearance) ? savedAppearance : 'system')
provide('workspaceAppearance', { appearance, chooseAppearance })
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
const compactNav = ref(false)
try { compactNav.value = localStorage.getItem('workspace-sidebar') === 'collapsed' } catch { /* 使用默认宽度。 */ }
function toggleSidebar() {
  compactNav.value = !compactNav.value
  try { localStorage.setItem('workspace-sidebar', compactNav.value ? 'collapsed' : 'expanded') } catch { /* 仍可在当前会话折叠。 */ }
}
const taskLinks = [
  ['diagnostics', 'warning', '分析结论'],
  ['sip', 'signal', 'SIP 信令'],
  ['media', 'wave', '媒体分析'],
  ['packets', 'file', '原始报文']
]
const health = ref(null)
const healthError = ref(false)

function applyTheme() {
  const root = document.documentElement
  root.dataset.appearance = appearance.value
  const next = appearance.value === 'system' ? (systemTheme.matches ? 'dark' : 'light') : appearance.value
  if (root.dataset.theme === next) return
  root.classList.add('changing-appearance')
  root.dataset.theme = next
  // Commit the new palette before restoring hover and focus transitions.
  void root.offsetWidth
  root.classList.remove('changing-appearance')
  window.dispatchEvent(new CustomEvent('alma-theme-changed', { detail: next }))
}

function chooseAppearance() {
  try { localStorage.setItem('appearance', appearance.value) } catch { /* 存储不可用时仅在当前窗口应用。 */ }
  applyTheme()
}

const engine = computed(() => {
  if (healthError.value) return ['服务离线', 'bad']
  if (!health.value) return ['正在连接', 'waiting']
  const tools = health.value.dependencies || {}
  if (!tools.tshark) return ['缺少 TShark', 'bad']
  if (!tools.ffmpeg || !tools.ffprobe) return ['分析可用 · 无视频预览', 'partial']
  if (!tools.capinfos) return ['分析可用 · 缺少 Capinfos', 'partial']
  if (!tools.dumpcap) return ['分析可用 · 实时采集不可用', 'partial']
  return ['分析引擎就绪', 'ok']
})

const task = computed(() => store.task)
const globalBusy = computed(() => store.activeCount > 0 || store.isAnalyzing)

function setNativeBusy(busy) {
  window.nsh?.postMessage?.(busy ? 'analysis-busy' : 'analysis-idle')
}

watch(globalBusy, (active) => {
  document.title = active
    ? '分析中 · GB28181 Analyzer'
    : 'GB28181 Analyzer · 视联网分析工作台'
  setNativeBusy(active)
}, { immediate: true })

function guardUnload(event) {
  if (!globalBusy.value) return
  event.preventDefault()
  event.returnValue = ''
}

let healthRequest = 0
let appUnmounted = false
async function loadHealth() {
  const request = ++healthRequest
  try {
    const value = await api.health()
    if (request !== healthRequest || appUnmounted) return
    health.value = value
    healthError.value = false
  } catch {
    if (request === healthRequest && !appUnmounted) healthError.value = true
  }
}

watch(() => [route.name, store.currentTaskId], ([name, id]) => {
  if (name && id && !store.task && name !== 'task' && name !== 'session-detail') {
    store.loadTask(id).catch(() => {})
  }
}, { immediate: true })

let healthTimer = null
let activeTimer = null

async function pollHealth() {
  await loadHealth()
  if (!appUnmounted) healthTimer = setTimeout(pollHealth, 30000)
}

async function pollActive() {
  await store.refreshActive()
  if (!appUnmounted) activeTimer = setTimeout(pollActive, 5000)
}

onMounted(() => {
  systemTheme.addEventListener('change', applyTheme)
  window.addEventListener('beforeunload', guardUnload)
  applyTheme()
  // Schedule the next request only after the previous one settles. This avoids
  // overlapping slow requests and prevents older responses winning the race.
  pollHealth()
  pollActive()
})

onUnmounted(() => {
  appUnmounted = true
  healthRequest++
  systemTheme.removeEventListener('change', applyTheme)
  window.removeEventListener('beforeunload', guardUnload)
  // 不清的话热更新会累积多个定时器，反复打健康检查
  if (healthTimer) { clearTimeout(healthTimer); healthTimer = null }
  if (activeTimer) { clearTimeout(activeTimer); activeTimer = null }
  setNativeBusy(false)
})
</script>

<template>
  <div class="app" :class="{ compact: compactNav }">
    <!-- 顶栏 -->
    <header class="bar">
      <div class="bar-in">
        <router-link to="/" class="brand" title="返回工作台">
          <img src="/brand/analyzer.svg" alt="" class="brand-logo" />
          <div class="brand-txt">
            <div class="brand-name">GB28181 Analyzer</div>
            <div class="brand-desc">GB/T 28181 协议与媒体分析工作站</div>
          </div>
        </router-link>

        <router-link class="bar-task" v-if="task" :to="{name: 'task', params: {id: task.id}}" title="打开当前任务">
          <span class="bt-id mono">#{{ task.id }}</span>
          <span class="badge" :class="{
            ok: task.status === 'completed',
            brand: task.status === 'analyzing',
            critical: task.status === 'failed',
            unknown: ['pending','cancelled'].includes(task.status)
          }">
            {{ { pending:'待分析', analyzing:'分析中', completed:'已完成',
                failed:'失败', cancelled:'已取消' }[task.status] }}
          </span>
          <span class="bt-name truncate">{{ task.file?.filename || task.name }}</span>
        </router-link>

        <div class="spacer"></div>

        <div class="bar-act">
          <select class="appearance" v-model="appearance" @change="chooseAppearance" aria-label="外观模式">
            <option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option>
          </select>

          <router-link to="/settings" class="nav-setting" aria-label="设置" title="设置"><AppIcon name="settings" /></router-link>
        </div>
      </div>
    </header>

    <aside class="sidebar">
      <button class="sidebar-toggle" type="button" :aria-expanded="!compactNav" aria-controls="workspace-nav"
              :title="compactNav ? '展开导航' : '折叠导航'" @click="toggleSidebar">
        <AppIcon :name="compactNav ? 'forward' : 'back'" /><span>{{ compactNav ? '展开导航' : '折叠导航' }}</span>
      </button>
      <nav id="workspace-nav" aria-label="主导航">
        <div class="nav-group">
          <span class="nav-heading">工作空间</span>
          <router-link to="/" :class="{ current: route.name === 'task' }" title="工作台"><AppIcon name="home" /><span>工作台</span></router-link>
          <router-link to="/tasks" title="历史任务"><AppIcon name="history" /><span>历史任务</span></router-link>
        </div>
        <div class="nav-group">
          <span class="nav-heading">当前任务</span>
          <router-link v-if="store.currentTaskId" :to="{ name: 'insight', query: { task: store.currentTaskId } }"
                       :class="{ current: route.name === 'insight' }"
                       title="智能洞察" aria-label="智能洞察"><AppIcon name="codec" /><span>智能洞察</span></router-link>
          <span v-else class="nav-disabled" aria-disabled="true" title="智能洞察 · 请先选择分析任务">
            <AppIcon name="codec" /><span>智能洞察</span>
          </span>
          <template v-for="[name, icon, label] in taskLinks" :key="name">
            <router-link v-if="store.currentTaskId" :to="{ name, query: { task: store.currentTaskId } }"
                         :class="{ current: route.name === name || (name === 'sip' && route.name === 'session-detail') }"
                         :title="label" :aria-label="label"><AppIcon :name="icon" /><span>{{ label }}</span></router-link>
            <span v-else class="nav-disabled" aria-disabled="true" :title="label + ' · 请先选择分析任务'">
              <AppIcon :name="icon" /><span>{{ label }}</span>
            </span>
          </template>
        </div>
        <div class="nav-group">
          <span class="nav-heading">辅助分析</span>
          <router-link to="/compare" :class="{ current: route.path.startsWith('/compare/') }" title="双包对比"><AppIcon name="compare" /><span>双包对比</span></router-link>
          <button type="button" class="ai-nav" :class="{ current: store.aiPanelOpen }" title="AI 专家会诊"
                  :aria-expanded="store.aiPanelOpen" data-cue="confirm" @click="openPageConsultation">
            <img src="/brand/deepseek.svg" alt="" width="16" height="16"><span>DeepSeek 会诊</span>
          </button>
        </div>
        <div class="nav-group">
          <span class="nav-heading">系统</span>
          <router-link to="/settings" title="系统设置"><AppIcon name="settings" /><span>系统设置</span></router-link>
        </div>
      </nav>
    </aside>

    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="route-slide" mode="out-in">
          <div class="route-surface" :key="JSON.stringify([route.path, route.query.task])"><component :is="Component" /></div>
        </transition>
      </router-view>
    </main>

    <footer class="status-bar" aria-label="工作区状态">
      <router-link to="/settings" class="dep" :class="engine[1]" :title="engine[0]"><i></i>{{ engine[0] }}</router-link>
      <span v-if="health?.dependencies" class="tool-status">TShark {{ health.dependencies.tshark ? '可用' : '缺失' }} · FFmpeg {{ health.dependencies.ffmpeg ? '可用' : '缺失' }}</span>
      <span v-if="task" class="status-task">任务 #{{ task.id }}<template v-if="task.stage"> · {{ task.stage }}</template></span>
      <span v-if="health?.version" class="version">v{{ health.version }}</span>
    </footer>

    <AiPanel v-if="aiPanelMounted" :key="store.currentTaskId" :open="store.aiPanelOpen"
             @update:open="v => v ? store.openAiPanel() : store.closeAiPanel()" />
  </div>
</template>

<style scoped>
.app {
  --sidebar-width: 184px;
  min-height: 100dvh;
  background: var(--bg);
  display: grid;
  grid-template: var(--app-header-height) 1fr var(--status-height) / var(--sidebar-width) minmax(0, 1fr);
}
.app.compact { --sidebar-width: 56px; }
.bar, .status-bar { grid-column: 1 / -1; position: sticky; background: var(--bg-2); z-index: 100; }
.bar { top: 0; border-bottom: 1px solid var(--line); }
.bar-in, .brand, .bar-task, .bar-act, .status-bar { display: flex; align-items: center; }
.bar-in { height: 100%; padding-inline: var(--space-4); gap: var(--space-5); }
.brand, .bar-task, .bar-act { gap: var(--space-2); }
.brand { flex: none; color: var(--text); }
.brand-logo { width: 24px; height: 24px; }
.brand-name { font-weight: 600; font-size: 15px; }
.brand-txt { display:flex; align-items:baseline; gap:14px; }
.brand-desc { font-size: 11px; color: var(--text-3); }
.bar-task { min-width: 0; color: var(--text-2); font-size: 12px; }
.bar-task .badge { white-space: nowrap; }
.spacer, .version { margin-left: auto; }
.bar-act { flex: none; }
.appearance, .nav-setting {
  background: var(--bg-input); color: var(--text);
  border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 4px 8px; height: 30px;
}
.nav-setting { display: grid; place-items: center; min-width: var(--control-height); }
.sidebar :is(a, button), .nav-setting {
  transition: background-color var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.sidebar {
  grid-column: 1; grid-row: 2; position: sticky; top: var(--app-header-height);
  height: calc(100dvh - var(--app-header-height) - var(--status-height));
  background: var(--bg-2); border-right: 1px solid var(--line);
  overflow: auto; padding: var(--space-2);
}
.sidebar :is(a, button, .nav-disabled) {
  display: flex; align-items: center; gap: var(--space-2); min-height: 34px;
  width: 100%; padding: 4px 10px; border: 0; border-inline-start: 3px solid transparent;
  border-radius: var(--radius-sm); background: transparent; color: var(--text-2);
  text-align: start; font: inherit; font-size: 13px; white-space: nowrap;
}
.sidebar .app-icon { flex: none; width: 16px; height: 16px; }
.sidebar :is(a, button):hover { background: var(--surface-3); text-decoration: none; }
.sidebar :is(.current, .router-link-exact-active) { color: var(--brand-lt); background: var(--bg-selected); border-inline-start-color: var(--brand); }
.sidebar .nav-disabled { opacity: .55; }
.sidebar .ai-nav { color:var(--ds-lt); background:var(--ds-soft); }
.nav-group { padding-block: 8px; border-top: 1px solid var(--line); }
.nav-heading { display: block; padding: 4px 13px; color: var(--text-4); font-size: 12px; }
.compact .sidebar :is(.nav-heading, a span, button span, .nav-disabled span) {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
}
.compact .sidebar :is(a, button, .nav-disabled) { padding-inline: 8px; }
.main { grid-column: 2; grid-row: 2; min-width: 0; }
.status-bar { bottom: 0; min-width: 0; gap: var(--space-4); padding-inline: var(--space-4); border-top: 1px solid var(--line); font-size: 11px; color: var(--text-3); overflow: hidden; white-space: nowrap; }
.dep { display: flex; align-items: center; gap: 6px; color: var(--text-2); }
.dep i { width: 6px; height: 6px; border-radius: 50%; background: var(--unknown); }
.dep.ok i { background: var(--ok); }
.dep.bad i { background: var(--critical); }
.dep.partial i { background: var(--warning); }
.status-task { overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 1100px) {
  .app { --sidebar-width: 56px; }
  .sidebar :is(.nav-heading, a span, button span, .nav-disabled span) {
    position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
  }
  .sidebar :is(a, button, .nav-disabled) { padding-inline: 8px; }
  .sidebar-toggle, .brand-desc { display: none !important; }
}
@media (max-width: 640px) {
  .bar-in { padding-inline: 8px; gap: 8px; }
  .bar-task, .tool-status { display: none; }
}
.route-surface { min-width:0; }
.route-slide-enter-active { transition: opacity var(--dur) var(--ease), translate var(--dur) var(--ease-out); }
.route-slide-leave-active { transition: opacity var(--dur-xs) var(--ease); }
.route-slide-enter-from { translate: 0 8px; }
.route-slide-enter-from, .route-slide-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .route-slide-enter-active, .route-slide-leave-active { transition: none; }
}
.sidebar { background:linear-gradient(165deg,var(--surface),var(--bg) 85%); padding:10px 8px; }
.nav-group { border-top:0; padding-block:9px; }
.nav-heading { font-weight:600; font-size:11px; padding-block:3px 8px; }
.sidebar :is(a,button,.nav-disabled) { min-height:36px; margin-bottom:2px; }
.sidebar :is(.current,.router-link-exact-active) { background:var(--bg-selected); color:var(--brand-lt); border-inline-start-color:var(--brand-lt); font-weight:650; }
.brand-name { letter-spacing:-.03em; }.bar .brand-logo { width:28px;height:28px; }
.bar { box-shadow:0 1px 6px rgb(0 0 0 / 4%); }
</style>
