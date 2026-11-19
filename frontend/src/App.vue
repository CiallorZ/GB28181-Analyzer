<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { api } from './api/client'
import { useTaskStore } from './stores/task'
import AiPanel from './components/AiPanel.vue'

const store = useTaskStore()

const theme = ref(localStorage.getItem('theme') || 'dark')
const health = ref(null)
const healthError = ref(false)

function applyTheme(t, animate = false) {
  // 加过渡类：让所有元素在切换瞬间统一过渡，避免局部闪烁
  if (animate) {
    document.documentElement.classList.add('theme-transition')
    setTimeout(() => {
      document.documentElement.classList.remove('theme-transition')
    }, 400)
  }
  theme.value = t
  document.documentElement.setAttribute('data-theme', t)
  localStorage.setItem('theme', t)
  // 通知图表重绘（ECharts 不会自动跟随 CSS 变量）
  window.dispatchEvent(new CustomEvent('alma-theme-changed', { detail: t }))
}
function toggleTheme() { applyTheme(theme.value === 'dark' ? 'light' : 'dark', true) }

const depsOk = computed(() => {
  if (!health.value) return false
  const d = health.value.dependencies || {}
  return d.tshark && d.ffmpeg
})

const task = computed(() => store.task)

async function loadHealth() {
  try {
    health.value = await api.health()
    healthError.value = false
  } catch { healthError.value = true }
}

let healthTimer = null

onMounted(() => {
  applyTheme(theme.value)
  loadHealth()
  if (store.currentTaskId) store.loadTask().catch(() => {})
  healthTimer = setInterval(loadHealth, 30000)
})

onUnmounted(() => {
  // 不清的话热更新会累积多个定时器，反复打健康检查
  if (healthTimer) { clearInterval(healthTimer); healthTimer = null }
})
</script>

<template>
  <div class="app">
    <!-- 顶栏 -->
    <header class="bar">
      <div class="bar-in">
        <router-link to="/" class="brand" title="返回工作台">
          <img :src="theme === 'dark' ? '/brand/logo-color-dark.png' : '/brand/logo-color-light.png'"
               alt="中国铁塔" class="brand-logo" />
          <div class="brand-txt">
            <div class="brand-name">GB28181 Analyzer</div>
            <div class="brand-desc">视联网协议分析与流媒体质量诊断</div>
          </div>
        </router-link>

        <div class="bar-task" v-if="task">
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
        </div>

        <div class="spacer"></div>

        <div class="bar-act">
          <router-link to="/tasks" class="icon-btn" title="历史任务">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path d="M12 8v4l3 2"/>
              <circle cx="12" cy="12" r="9"/>
            </svg>
          </router-link>
          <button class="icon-btn" @click="toggleTheme"
                  :title="theme === 'dark' ? '切换到浅色' : '切换到深色'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <template v-if="theme === 'dark'">
                <circle cx="12" cy="12" r="4.2"/>
                <path d="M12 2.5v2M12 19.5v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2.5 12h2M19.5 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>
              </template>
              <path v-else d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
            </svg>
          </button>

          <button class="ai-btn" aria-label="DeepSeek 分析" @click="store.openAiPanel()">
            <img src="/brand/deepseek-white.svg" alt="" class="ai-ico" />
            <span>DeepSeek 分析</span>
          </button>

          <div class="dep" :class="depsOk ? 'ok' : 'bad'"
               :title="healthError ? '服务离线' : (depsOk ? 'tshark / ffmpeg 就绪' : '依赖缺失')">
            <i></i>
            <span>{{ healthError ? '离线' : (depsOk ? '就绪' : '缺依赖') }}</span>
          </div>
        </div>
      </div>
    </header>

    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <AiPanel :open="store.aiPanelOpen"
             @update:open="v => v ? store.openAiPanel() : store.closeAiPanel()" />
  </div>
</template>

<style scoped>
.app { min-height: 100vh; display: flex; flex-direction: column; }

/* 顶栏 */
.bar {
  position: sticky; top: 0; z-index: 100;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: blur(16px) saturate(160%);
  border-bottom: 1px solid var(--line);
}
.bar-in {
  max-width: 1720px; margin: 0 auto;
  height: 58px; padding: 0 28px;
  display: flex; align-items: center; gap: 20px;
}
@media (max-width: 1080px) { .bar-in { padding: 0 16px; gap: 12px; } }

.brand {
  display: flex; align-items: center; gap: 12px; flex: none;
  padding: 4px 8px; margin-left: -8px;
  border-radius: var(--radius-sm);
  transition: background var(--dur) var(--ease);
}
.brand:hover { background: var(--surface); text-decoration: none; }
.brand-logo {
  height: 30px; width: auto; display: block;
  transition: opacity var(--dur) var(--ease);
}
.brand-txt { line-height: 1.25; }
.brand-name {
  font-size: 15.5px; font-weight: 700;
  letter-spacing: -.2px;
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
  background: var(--ds);
  border: 1px solid var(--ds);
  color: #fff;
  font-size: 12.5px; font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background-color var(--dur) var(--ease),
              border-color var(--dur) var(--ease);
}
.ai-btn:hover {
  background: var(--ds-dk);
  border-color: var(--ds-dk);
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

.main { flex: 1; }

/* 移动端：只留标志与图标，任务上下文交给页面标题 */
@media (max-width: 720px) {
  .bar-in { padding: 0 12px; gap: 8px; }
  .bar-task { display: none; }
  .brand-desc { display: none; }
  .brand-name { font-size: 13px; }
  .brand-logo { height: 24px; }
  .bar-act { gap: 6px; }
  .icon-btn { width: 30px; height: 30px; }
  .ai-btn { width: 30px; padding: 0; justify-content: center; }
  .ai-btn span { display: none; }
  .dep { padding: 0 8px; }
  .dep span { display: none; }
}

.fade-enter-active, .fade-leave-active {
  transition: opacity .16s var(--ease);
}
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
