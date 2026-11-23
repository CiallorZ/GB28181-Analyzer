<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api/client'
import { useTaskStore } from './stores/task'
import AiPanel from './components/AiPanel.vue'

const store = useTaskStore()
const route = useRoute()

const appearance = ref(document.documentElement.dataset.appearance || 'system')
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
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
  if (!health.value.dependencies.tshark) return ['缺少 TShark', 'bad']
  if (!health.value.dependencies.ffmpeg) return ['分析可用 · 无视频预览', 'partial']
  return ['分析引擎就绪', 'ok']
})

const task = computed(() => store.task)

async function loadHealth() {
  try {
    health.value = await api.health()
    healthError.value = false
  } catch { healthError.value = true }
}

watch(() => [route.name, store.currentTaskId], ([name, id]) => {
  if (name && id && !store.task && name !== 'task' && name !== 'session-detail') {
    store.loadTask(id).catch(() => {})
  }
}, { immediate: true })

let healthTimer = null

onMounted(() => {
  systemTheme.addEventListener('change', applyTheme)
  applyTheme()
  loadHealth()

  healthTimer = setInterval(loadHealth, 30000)
})

onUnmounted(() => {
  systemTheme.removeEventListener('change', applyTheme)
  // 不清的话热更新会累积多个定时器，反复打健康检查
  if (healthTimer) { clearInterval(healthTimer); healthTimer = null }
})
</script>

<template>
  <div class="app">
    <!-- 顶栏 -->
    <header class="bar glass-panel">
      <div class="bar-in">
        <router-link to="/" class="brand" title="返回工作台">
          <img src="/brand/analyzer.svg" alt="中国铁塔" class="brand-logo" />
          <div class="brand-txt">
            <div class="brand-name">GB28181 Analyzer</div>
            <div class="brand-desc">GB/T 28181 协议与媒体分析工作站</div>
          </div>
        </router-link>

          <router-link to="/settings" class="dep" :class="engine[1]" :title="engine[0]" :aria-label="engine[0]">
            <i></i>
            <span>{{ engine[0] }}</span>
          </router-link>
        <nav class="bar-nav" aria-label="主导航">
          <router-link to="/" :class="{current: route.name === 'task'}"><AppIcon name="home" />工作台</router-link>
          <router-link to="/tasks"><AppIcon name="history" />历史任务</router-link>
          <router-link to="/compare" :class="{current: route.path.startsWith('/compare/')}"><AppIcon name="compare" />双包对比</router-link>
          <router-link to="/settings"><AppIcon name="settings" />设置</router-link>
        </nav>

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

          <button class="ai-btn" data-cue="confirm" aria-label="DeepSeek 分析" @click="store.openAiPanel()">
            <img src="/brand/deepseek.svg" alt="" class="ai-ico" />
            <span>AI 分析助手</span>
          </button>


        </div>
      </div>
    </header>

    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="route-slide" mode="out-in">
          <component :is="Component" :key="route.name === 'session-detail' ? route.path : route.query.task" />
        </transition>
      </router-view>
    </main>

    <AiPanel :key="store.currentTaskId" :open="store.aiPanelOpen"
             @update:open="v => v ? store.openAiPanel() : store.closeAiPanel()" />
  </div>
</template>

<style scoped>
.app { min-height: 100vh; display: flex; flex-direction: column; }

/* 顶栏 */
.bar {
  position: sticky; top: 0; z-index: 100;
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  backdrop-filter: blur(16px) saturate(160%);
  border-bottom: 1px solid var(--line);
  box-shadow: inset 0 3px 0 var(--brand);
}
.bar-in {
  max-width: 1720px; margin: 0 auto;
  height: calc(var(--app-header-height) - 1px); padding: 0 28px;
  display: flex; align-items: center; gap: 26px;
}
.bar-nav { display: flex; align-items: stretch; align-self: stretch; gap: 8px; white-space: nowrap; }
.bar-nav a { gap:6px; position: relative; display:flex; align-items:center; padding: 0 12px; color: var(--text-2); font-size: 13px; font-weight: 600; }
.bar-nav a:hover, .bar-nav .router-link-exact-active, .bar-nav .current {
  color: var(--brand-lt); text-decoration: none;
}
@media (max-width: 1080px) { .bar-in { padding: 0 16px; gap: 12px; } }

.brand {
  display: flex; align-items: center; gap: 12px; flex: none;
  padding: 4px 24px 4px 8px; margin-left: -8px;
  border-right: 1px solid var(--line-2);
  transition: background var(--dur) var(--ease);
}
.brand:hover { background: var(--surface); text-decoration: none; }
.brand-logo {
  height: 30px; width: auto; display: block;
  transition: opacity var(--dur) var(--ease);
}
.brand-txt { line-height: 1.25; }
.brand-name {
  font-size: 15px; font-weight: 700;
  letter-spacing: -.35px;
  color: var(--brand-lt);
}
.brand-desc {
  font-size: 11px; color: var(--text-4);
  letter-spacing: .01em;
}

.bar-task {
  display: flex; align-items: center; gap: 9px;
  padding: 5px 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 99px;
  font-size: 12px;
  max-width: 440px;
  overflow: hidden;
}
.bt-id { color: var(--text-3); font-weight: 600; font-size: 11.5px; }
.bt-name { color: var(--text-2); min-width: 0; }

.bar-act { display: flex; align-items: center; gap: 10px; flex: none; }

.icon-btn {
  width: 34px; height: 34px; flex: none;
  border-radius: var(--radius-sm);
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-3);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--dur) var(--ease);
  text-decoration: none;
}
.icon-btn:hover {
  border-color: var(--line-strong);
  background: var(--surface-2);
  color: var(--text);
}
.icon-btn svg { width: 16px; height: 16px; }

.ai-btn {
  display: inline-flex; align-items: center; gap: 7px;
  height: 34px; padding: 0 14px;
  border-radius: var(--radius-sm);
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
  color: var(--ds-lt);
  font-size: 12.5px; font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background-color var(--dur) var(--ease),
              border-color var(--dur) var(--ease);
}
.ai-btn:hover {
  background: var(--surface-3);
  border-color: var(--ds-lt);
}
.ai-ico { height: 14px; width: auto; }

.dep {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--text-3);
  padding: 0 11px; height: 28px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 99px;
}
.dep i { width: 6px; height: 6px; border-radius: 50%; flex: none; }
.dep.ok i { background: var(--ok); }
.dep.bad i { background: var(--critical); }
.dep.partial i { background: var(--warning); }
.dep.waiting i { background: var(--text-3); }

.main { flex: 1; min-width: 0; }

/* 移动端：只留标志与图标，任务上下文交给页面标题 */
@media (max-width: 1020px) {
  .bar-task { display: none; }
  .dep span { display: none; }
}
@media (max-width: 650px) {
  .bar-in { padding: 0 12px; gap: 8px; }
  .bar-in { flex-wrap: wrap; padding-top: 8px; }
  .bar-nav { order: 2; flex-basis: 100%; height: 35px; gap: 6px; }
  .bar-nav { justify-content:space-between; min-width:0; }
  .bar-nav a { padding:0 3px; gap:4px; }
  .brand { border-right: 0; padding-right: 4px; }
  .brand-desc { display: none; }
  .brand-name { font-size: 13px; }
  .brand-logo { height: 24px; width: auto; }
  .bar-act { gap: 6px; }
  .icon-btn { width: 30px; height: 30px; }
  .ai-btn { width: 30px; padding: 0; justify-content: center; }
  .ai-btn span { display: none; }
  .dep { padding: 0 8px; }
  .dep span { display: none; }
}

.route-slide-enter-active { transition: opacity .2s var(--ease), translate .24s var(--ease-out); }
.route-slide-leave-active { transition: opacity .07s ease-in; }
.route-slide-enter-from { opacity:0; translate:0 7px; }
.route-slide-leave-to { opacity:0; }
.bar-nav a { transition:color .16s var(--ease), background-color .16s var(--ease); }
.bar-nav a {
  align-self:center;
  min-height:34px;
  border-radius:var(--radius-sm);
}
.bar-nav a:is(.router-link-exact-active,.current) {
  background:var(--brand-soft);
  color:var(--brand-lt);
}
.bar-nav a:not(.router-link-exact-active,.current):hover { background:var(--surface-2); }
.bar-nav a:is(.router-link-exact-active,.current) .app-icon { color:var(--brand-lt); }
.bar-nav a .app-icon { width:16px; height:16px; }
@media (max-width:1279px) { .bar .brand-desc { display:none; } }
@media (max-width:900px) {
  .bar-in { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 10px; padding:6px 12px 0; }
  .bar .brand { border:0; padding-right:0; }
  .bar .spacer { display:none; }
  .bar .bar-nav { grid-row:2; grid-column:1/-1; justify-content:space-between; min-width:0; }
  .bar-nav a { gap:5px; padding:0 clamp(2px,1vw,10px); }
  .bar-nav a .app-icon { width:14px; height:14px; }
  .bar-act { grid-column:2; grid-row:1; }
}
@media (max-width:360px) {
  .brand-logo { height:20px; }
  .bar-nav { gap:3px; }
  .bar-nav a { font-size:12px; }
}
.appearance {background:var(--surface);color:var(--text-2);border:1px solid var(--line-2);border-radius:6px;font:inherit;font-size:12px;padding:5px;}
@media(min-width:1081px){.bar-in{max-width:none;padding:0 20px;gap:20px}.brand-txt{display:flex;align-items:center;gap:18px}.brand-desc{font-size:12px;border-left:1px solid var(--line);padding-left:16px}.bar-task{display:none}.bar{box-shadow:none}}
.brand .brand-name{color:var(--text)}@media(min-width:1100px){.bar-in{gap:18px}.dep{border-radius:5px}.bar-nav{margin-left:12px}}@media(max-width:1100px){.bar-in>.dep{display:none}}
</style>
