<script setup>
/**
 * DeepSeek 会诊面板
 *
 * 三个阶段：确认配置 → 选择专家并确认发送内容 → 研判报告与追问。
 * 视觉沿用应用本身的仪器面板语言：1px 细线、小圆角、蓝色只作为 AI 强调色。
 */
import { defineAsyncComponent, ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import { api } from '../api/client'
import AiContextPreview from './AiContextPreview.vue'
import InterfaceState from './InterfaceState.vue'
import { feedback } from '../stores/interface'
import { useTaskStore } from '../stores/task'
import { renderMd } from '../utils/markdown'
import { AI_STEPS, resolvePhase, stepIndexFor } from '../utils/aiStages'

const AiExpertPicker = defineAsyncComponent(() => import('./AiExpertPicker.vue'))

const props = defineProps({ open: Boolean })
const emit = defineEmits(['update:open'])

const store = useTaskStore()

const view = ref('flow')            // 'config' | 'flow'
const drawerRef = ref(null)
const bodyRef = ref(null)
let previousFocus = null

const report = ref('')
const previewOpen = ref(false)
const reportContextHash = ref('')
const reportSeconds = ref('')
const reportExpert = ref('general')
let reportController = null
let chatController = null
onUnmounted(() => { reportController?.abort(); chatController?.abort() })

const running = ref(false)
const err = ref('')
const copied = ref(false)

const chat = ref([])
const question = ref('')
const chatBusy = ref(false)
const questionInput = ref(null)

const expert = ref('general')
const profiles = {
  general: ['综合研判', '串联信令、媒体与规则证据', ['第一处异常出现在哪里？', '哪些结论仍需补抓验证？']],
  sip: ['信令事务', '追踪请求、响应与重传', ['哪个事务缺少最终响应？', '重传与明确拒绝如何区分？']],
  media: ['媒体链路', '核对 SSRC、丢包与画面', ['协商和实际 SSRC 是否一致？', '画面重建失败有哪些可验证原因？']],
  packet: ['报文取证', '从报文特征核对诊断结论', ['哪些报文编号能支撑当前结论？', '哪些协议字段或端点需要人工复核？']],
  field: ['现场排障', '制定两端复核步骤', ['平台侧先检查什么？', '下一次应在哪一端抓包？']]
}
const suggestedQuestions = computed(() => profiles[expert.value][2])
const expertName = computed(() => profiles[expert.value][0])
const requestedExpert = computed(() => Object.hasOwn(profiles, store.aiFocus) ? store.aiFocus : 'general')

function useSuggestion(text) {
  question.value = text
  nextTick(() => {
    questionInput.value?.focus()
    autoGrow()
  })
}

const cfg = ref({ has_key: false, key_hint: '', model: '', base_url: '' })
const keyInput = ref('')
const modelInput = ref('')
const baseInput = ref('')
const cfgMsg = ref('')
const cfgMsgOk = ref(false)
const cfgBusy = ref(false)
const testing = ref(false)

const canAnalyze = computed(() => store.task && store.task.status === 'completed')

const facts = computed(() => {
  const s = store.task?.summary || {}
  const d = s.diagnostics || {}
  return [
    { k: '报文', v: (s.packet_count ?? '—').toLocaleString() },
    { k: '会话', v: s.session_count ?? '—' },
    { k: '信令成功', v: s.signal_success_rate != null ? s.signal_success_rate.toFixed(1) + '%' : '—' },
    { k: '有媒体', v: s.sessions_with_media ?? '—' },
    { k: '严重', v: d.critical ?? '—', tone: d.critical ? 'critical' : '' },
    { k: '警告', v: d.warning ?? '—', tone: d.warning ? 'warning' : '' }
  ]
})

/* 阶段：配置 → 选择 → 确认发送 → 研判结果 */
const phase = computed(() => resolvePhase({
  view: view.value,
  report: report.value,
  running: running.value,
  previewOpen: previewOpen.value
}))

watch(phase, async () => {
  await nextTick()
  const drawer = drawerRef.value
  if (props.open && drawer && !drawer.contains(document.activeElement)) {
    drawer.focus({ preventScroll: true })
  }
})

const stepIndex = computed(() => stepIndexFor(phase.value))

const taskName = computed(() => store.task?.file?.filename || store.task?.name || '')

const close = () => emit('update:open', false)

function onDrawerKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (event.key !== 'Tab') return
  const controls = [...(drawerRef.value?.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex="0"]') || [])]
    .filter(element => element.getClientRects().length)
  if (!controls.length) { event.preventDefault(); drawerRef.value?.focus(); return }
  const first = controls[0], last = controls[controls.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === drawerRef.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

function scrollBody(toTop) {
  nextTick(() => {
    const el = bodyRef.value
    if (el && toTop) el.scrollTop = 0
  })
}


/* ---------------- 配置 ---------------- */
async function loadCfg() {
  try {
    cfg.value = await api.aiConfig()
    modelInput.value = cfg.value.model || ''
    baseInput.value = cfg.value.base_url || ''
  } catch { /* 读取失败时保持默认，用户仍可手动填写 */ }
}

async function saveCfg() {
  cfgBusy.value = true
  cfgMsg.value = ''
  cfgMsgOk.value = false
  try {
    const body = {}
    if (keyInput.value.trim()) body.api_key = keyInput.value.trim()
    if (modelInput.value.trim()) body.model = modelInput.value.trim()
    if (baseInput.value.trim()) body.base_url = baseInput.value.trim()
    cfg.value = await api.aiSaveConfig(body)
    keyInput.value = ''
    cfgMsg.value = '已保存，可以开始会诊'
    cfgMsgOk.value = true
    feedback('success')
    if (cfg.value.has_key) view.value = 'flow'
  } catch (e) {
    cfgMsg.value = '保存失败：' + e.message
  } finally {
    cfgBusy.value = false
  }
}

async function testConn() {
  testing.value = true
  cfgMsg.value = ''
  cfgMsgOk.value = false
  try {
    const r = await api.aiTest()
    cfgMsg.value = '连接正常：' + (r.reply || 'OK')
    cfgMsgOk.value = true
  } catch (e) {
    cfgMsg.value = '连接失败：' + e.message
  } finally {
    testing.value = false
  }
}

/* ---------------- 报告 ---------------- */
async function runAnalyze(contextHash) {
  previewOpen.value = false
  if (running.value || !canAnalyze.value) return
  if (!cfg.value.has_key) { view.value = 'config'; return }

  running.value = true
  err.value = ''
  report.value = ''
  reportContextHash.value = ''
  reportSeconds.value = ''
  chat.value = []
  reportExpert.value = expert.value
  const t0 = Date.now()
  reportController = new AbortController()
  scrollBody(true)

  try {
    const res = await fetch('/api/v1/ai/analyze/' + store.currentTaskId, {
      method: 'POST',
      signal: reportController.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expert: expert.value, context_hash: contextHash })
    })
    if (!res.ok || !res.body) {
      let m = 'HTTP ' + res.status
      try { const j = await res.json(); if (j.error || j.detail) m = j.error || j.detail } catch { /* 非 JSON 响应 */ }
      throw new Error(m)
    }

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = '', acc = '', completed = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        let ev = 'message', data = ''
        block.split('\n').forEach(l => {
          if (l.startsWith('event:')) ev = l.slice(6).trim()
          else if (l.startsWith('data:')) data += l.slice(5).trim()
        })
        if (!data) continue
        let j
        try { j = JSON.parse(data) } catch { continue }

        if (ev === 'delta') {
          acc += j.t || ''
          report.value = acc
        } else if (ev === 'done') {
          completed = true
          report.value = j.text || acc
        } else if (ev === 'error') {
          throw new Error(j.error || '分析失败')
        }
      }
    }
    if (!completed) throw new Error('连接中断，分析结果可能不完整，请重试')
    if (!report.value.trim()) throw new Error('模型没有返回内容')
    reportContextHash.value = contextHash
    reportSeconds.value = ((Date.now() - t0) / 1000).toFixed(1)
    feedback('success')
    scrollBody(true)
  } catch (e) {
    report.value = ''
    err.value = e.name === 'AbortError' ? '已停止接收报告。已发出的请求仍可能由服务端处理。' : e.message
    if (e.name !== 'AbortError') feedback('error')
  } finally {
    running.value = false
    reportController = null
  }
}


/* ---------------- 追问 ---------------- */
function autoGrow() {
  const el = questionInput.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 132) + 'px'
}

function composerKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.shiftKey) return
  event.preventDefault()
  sendQuestion()
}

async function sendQuestion() {
  const q = question.value.trim()
  if (!q || chatBusy.value || running.value || !reportContextHash.value || !store.currentTaskId) return

  feedback('send')
  question.value = ''
  nextTick(autoGrow)
  const userMessage = reactive({ role: 'user', content: q })
  chat.value.push(userMessage)
  const history = chat.value.slice(0, -1).filter(m => !m.failed).map(m => ({
    role: m.role, content: m.content
  }))
  history.unshift({ role: 'assistant', content: report.value })
  const slot = reactive({ role: 'assistant', content: '', streaming: true })
  chat.value.push(slot)
  chatBusy.value = true
  chatController = new AbortController()
  await nextTick()
  scrollChat()

  try {
    const res = await fetch('/api/v1/ai/chat/' + store.currentTaskId, {
      method: 'POST',
      signal: chatController.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history, expert: expert.value, context_hash: reportContextHash.value })
    })
    if (!res.ok || !res.body) {
      let m = 'HTTP ' + res.status
      try { const j = await res.json(); if (j.error || j.detail) m = j.error || j.detail } catch { /* 非 JSON 响应 */ }
      throw new Error(m)
    }

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = '', acc = '', completed = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        let ev = 'message', data = ''
        block.split('\n').forEach(l => {
          if (l.startsWith('event:')) ev = l.slice(6).trim()
          else if (l.startsWith('data:')) data += l.slice(5).trim()
        })
        if (!data) continue
        let j
        try { j = JSON.parse(data) } catch { continue }
        if (ev === 'delta') {
          acc += j.t || ''
          slot.content = acc
          scrollChat()
        } else if (ev === 'done') {
          completed = true
          slot.content = j.text || acc
        } else if (ev === 'error') {
          throw new Error(j.error || '对话失败')
        }
      }
    }
    if (!completed) throw new Error('连接中断，回答不完整，请重试')
    if (!slot.content.trim()) throw new Error('模型没有返回内容')
    feedback('success')
  } catch (e) {
    userMessage.failed = true
    slot.failed = true
    slot.content = '对话失败：' + e.message
    if (e.name !== 'AbortError') feedback('error')
  } finally {
    slot.streaming = false
    chatBusy.value = false
    chatController = null
    scrollChat()
  }
}

function scrollChat() {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

/* ---------------- 报告动作 ---------------- */
function exportReport() {
  const url = URL.createObjectURL(new Blob([report.value], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'DeepSeek-分析-' + store.currentTaskId + '.md'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function copyReport() {
  try {
    await navigator.clipboard?.writeText(report.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1600)
  } catch { copied.value = false }
}

function resetReport() {
  expert.value = requestedExpert.value
  report.value = ''
  reportContextHash.value = ''
  reportSeconds.value = ''
  chat.value = []
  question.value = ''
  err.value = ''
  previewOpen.value = false
  scrollBody(true)
}

/* 全屏抽屉打开时锁住页面滚动，否则手机上背后的结果页会一起滚 */
let previousOverflow = ''

function lockPageScroll() {
  previousOverflow = document.documentElement.style.overflow
  document.documentElement.style.overflow = 'hidden'
}

function unlockPageScroll() {
  document.documentElement.style.overflow = previousOverflow
}

watch(() => props.open, async (v) => {
  if (!v) {
    unlockPageScroll()
    previousFocus?.focus?.()
    previousFocus = null
    return
  }
  if (!report.value && !running.value && !previewOpen.value) expert.value = requestedExpert.value
  previousFocus = document.activeElement
  lockPageScroll()
  await nextTick()
  drawerRef.value?.focus()
  view.value = 'flow'
  await loadCfg()
}, { immediate: true })
onUnmounted(() => { if (props.open) unlockPageScroll() })

onUnmounted(unlockPageScroll)
</script>


<template>
  <Teleport to="body">
    <Transition name="ai-slide">
      <div v-if="open" class="ai-mask" @click.self="close">
        <aside
          ref="drawerRef"
          class="ai-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="DeepSeek 会诊"
          tabindex="-1"
          @keydown="onDrawerKeydown"
        >
          <header class="ai-head">
            <span class="ai-mark" aria-hidden="true"><img src="/brand/deepseek.svg" alt="" /></span>
            <div class="ai-head-text">
              <strong>DeepSeek 会诊</strong>
              <span class="ai-head-sub">
                <template v-if="taskName">{{ taskName }}</template>
                <template v-else>尚未选择任务</template>
                <template v-if="cfg.model"> · <span class="mono">{{ cfg.model }}</span></template>
              </span>
            </div>
            <div class="ai-head-acts">
              <button
                v-if="phase !== 'config'"
                type="button"
                class="ai-icon-btn"
                title="连接设置"
                aria-label="连接设置"
                @click="view = 'config'"
              ><AppIcon name="settings" /></button>
              <button type="button" class="ai-icon-btn" title="关闭" aria-label="关闭会诊" @click="close">
                <AppIcon name="close" />
              </button>
            </div>
          </header>

          <nav v-if="view === 'flow' && canAnalyze" class="ai-steps" aria-label="会诊流程">
            <template v-for="(label, i) in AI_STEPS" :key="label">
              <span class="ai-step" :class="{ on: stepIndex === i, done: stepIndex > i }">
                <i aria-hidden="true">{{ stepIndex > i ? '✓' : i + 1 }}</i>{{ label }}
              </span>
              <span v-if="i < 2" class="ai-step-line" :class="{ done: stepIndex > i }" aria-hidden="true"></span>
            </template>
          </nav>

          <div ref="bodyRef" v-panel-change="phase" class="ai-body">
            <p v-if="err && view === 'flow' && !previewOpen" class="ai-msg bad" role="alert">{{ err }}</p>
            <div v-if="view === 'config'" class="ai-config">
              <div class="ai-note">
                <span class="ai-note-icon" aria-hidden="true"><AppIcon name="info" /></span>
                <div>
                  <strong>只发送结构化摘要</strong>
                  <p>会话、流与规则结论会发送给模型服务，抓包原始字节不会离开本机。API Key 只保存在本机后端，前端仅显示末四位。</p>
                </div>
              </div>

              <div class="ai-field">
                <label for="ai-key">API Key</label>
                <input
                  id="ai-key"
                  v-model="keyInput"
                  type="password"
                  class="inp"
                  autocomplete="off"
                  :placeholder="cfg.has_key ? '已配置 ' + cfg.key_hint + '，留空则不修改' : 'sk-…'"
                />
                <p class="ai-hint">在 <a href="https://platform.deepseek.com/" target="_blank" rel="noopener noreferrer">DeepSeek 开放平台</a> 创建密钥，保存到本机数据目录。</p>
              </div>

              <div class="ai-field">
                <label for="ai-model">模型 ID</label>
                <input id="ai-model" v-model="modelInput" type="text" class="inp" placeholder="deepseek-flash" spellcheck="false" />
                <p class="ai-hint">填当前账号已开通的模型，留空使用默认值。</p>
              </div>

              <div class="ai-field">
                <label for="ai-base">接口地址</label>
                <input id="ai-base" v-model="baseInput" type="text" class="inp" placeholder="https://api.deepseek.com" spellcheck="false" />
                <p class="ai-hint">使用自建网关时填写完整地址，需为 HTTPS。</p>
              </div>

              <p v-if="cfgMsg" class="ai-msg" :class="cfgMsgOk ? 'ok' : 'bad'" role="status">{{ cfgMsg }}</p>

              <div class="ai-config-acts">
                <button type="button" class="btn primary" :disabled="cfgBusy" @click="saveCfg">
                  {{ cfgBusy ? '保存中…' : '保存设置' }}
                </button>
                <button type="button" class="btn" :disabled="testing || !cfg.has_key" @click="testConn">
                  {{ testing ? '测试中…' : '测试连接' }}
                </button>
                <button v-if="canAnalyze" type="button" class="btn ghost" @click="view = 'flow'">返回会诊</button>
              </div>
            </div>

            <template v-else>
              <InterfaceState
                v-if="!canAnalyze"
                icon="signal"
                title="先完成一次抓包分析"
                detail="选择已完成的抓包后，可以在本机查看会诊依据，选择信令或媒体分析视角。"
              >
                <router-link class="btn primary" to="/tasks" @click="close">选择历史任务</router-link>
                <router-link class="btn" to="/" @click="close">导入抓包</router-link>
              </InterfaceState>

              <template v-else>
                <AiContextPreview
                  v-if="phase === 'preview'"
                  :task-id="store.currentTaskId"
                  :expert="expertName"
                  :model-endpoint="cfg.base_url"
                  :connected="cfg.has_key"
                  @configure="view = 'config'"
                  @cancel="previewOpen = false"
                  @confirm="runAnalyze"
                />

                <div v-else-if="phase === 'choose'" class="consult-grid">
                  <section class="ai-block consult-roles">
                    <h3 class="ai-block-title">选择会诊视角</h3>
                    <p v-if="requestedExpert !== 'general'" class="ai-focus-note">当前页面建议：{{ profiles[requestedExpert][0] }}</p>
                    <AiExpertPicker v-model="expert" :profiles="profiles" />
                  </section>
                  <section class="ai-block perspective">
                    <header class="perspective-head">
                      <span class="perspective-logo"><img src="/brand/deepseek.svg" alt="" width="28"></span>
                      <div><small>当前会诊视角</small><h3>{{ expertName }}</h3></div>
                    </header>
                    <div :key="expert" class="perspective-body">
                      <h4>优先核实的问题</h4>
                      <ul><li v-for="item in suggestedQuestions" :key="item">{{ item }}</li></ul>
                    </div>
                  </section>
                  <section class="ai-block">
                    <h3 class="ai-block-title">发送给 DeepSeek 的证据</h3>
                    <p class="ai-hint">证据来自当前任务的结构化摘要。抓包原始字节保留在本机。</p>
                    <dl class="ai-facts">
                      <div v-for="f in facts" :key="f.k">
                        <dt>{{ f.k }}</dt>
                        <dd :class="f.tone">{{ f.v }}</dd>
                      </div>
                    </dl>
                  </section>
                  <div class="ai-run">
                    <button type="button" class="btn primary lg" @click="previewOpen = true">
                      预览会诊请求 <AppIcon name="forward" />
                    </button>
                    <span class="ai-hint">预览会诊视角、证据摘要与接收地址后再确认发送。</span>
                  </div>
                </div>

                <template v-else>
                  <div v-if="running && !report" class="ai-running" role="status">
                    <span class="ai-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                    <span>正在生成研判报告，通常需要十几秒</span>
                  </div>

                  <button v-if="running" type="button" class="btn" @click="reportController?.abort()">
                    停止接收
                  </button>

                  <article v-if="report" class="ai-report">
                    <header class="ai-report-head">
                      <div class="arh-text">
                        <h3>{{ profiles[reportExpert][0] }} · 研判报告</h3>
                        <p>
                          任务 #{{ store.currentTaskId }}
                          <template v-if="reportSeconds"> · 用时 {{ reportSeconds }}s</template>
                          <template v-if="report.length"> · {{ report.length.toLocaleString() }} 字</template>
                        </p>
                      </div>
                      <div class="arh-acts">
                        <button type="button" class="btn-mini" @click="copyReport">{{ copied ? '已复制' : '复制' }}</button>
                        <button type="button" class="btn-mini" @click="exportReport">导出 .md</button>
                        <button type="button" class="btn-mini" :disabled="running" @click="previewOpen = true">重新分析</button>
                        <button type="button" class="btn-mini" :disabled="running || chatBusy" @click="resetReport">新会诊</button>
                      </div>
                    </header>
                    <p class="ai-focus-note">AI 辅助研判 · 请按报告中的证据编号回查抓包。</p>
                    <div class="ai-md" v-html="renderMd(report)"></div>
                  </article>

                  <section v-if="report" class="ai-thread" aria-label="会诊对话">
                    <h4 class="ai-thread-title">
                      追问
                      <span v-if="!chat.length" class="ai-thread-hint">报告里的结论可以继续追问</span>
                    </h4>

                    <div v-for="(m, i) in chat" :key="i" class="ai-msg-row" :class="m.role">
                      <span class="ai-avatar" :class="m.role" aria-hidden="true">
                        <img v-if="m.role === 'assistant'" src="/brand/deepseek.svg" alt="" />
                        <template v-else>我</template>
                      </span>
                      <div class="ai-bubble" :class="{ failed: m.failed }">
                        <div v-if="m.role === 'assistant'" class="ai-md" v-html="renderMd(m.content)"></div>
                        <p v-else class="ai-user-text">{{ m.content }}</p>
                        <span v-if="m.streaming" class="ai-caret" aria-hidden="true"></span>
                      </div>
                      <button
                        v-if="m.role === 'user' && m.failed && !chatBusy"
                        type="button"
                        class="btn-mini ai-retry"
                        @click="useSuggestion(m.content)"
                      >填回输入框</button>
                    </div>

                    <div v-if="!chatBusy && reportContextHash" class="ai-followups">
                      <span>接着问</span>
                      <button
                        v-for="prompt in suggestedQuestions"
                        :key="prompt"
                        type="button"
                        @click="useSuggestion(prompt)"
                      >{{ prompt }}</button>
                    </div>
                  </section>
                </template>
              </template>
            </template>
          </div>

          <footer v-if="phase === 'result' && report" class="ai-composer">
            <div class="ai-input">
              <textarea
                ref="questionInput"
                v-model="question"
                rows="1"
                aria-label="输入追问"
                :disabled="running || !reportContextHash"
                placeholder="继续追问，例如：这个 SSRC 要去哪里改？"
                @input="autoGrow"
                @keydown.enter="composerKeydown"
              ></textarea>
              <button
                type="button"
                class="ai-send"
                aria-label="发送追问"
                :disabled="chatBusy || running || !reportContextHash || !question.trim()"
                @click="sendQuestion"
              ><AppIcon name="send" /><span>发送</span></button>
            </div>
            <p class="ai-composer-hint">
              <span v-if="chatBusy">正在回答…</span>
              <template v-else>Enter 发送 · Shift + Enter 换行</template>
              <span class="ai-composer-warn">对话内容不做脱敏，请勿粘贴敏感信息</span>
            </p>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>


<style scoped>
.ai-mask {
  position: fixed; inset: 0; z-index: 300;
  display: flex; justify-content: flex-end;
  background: color-mix(in srgb, var(--bg) 46%, transparent);
}

.ai-drawer {
  display: flex; flex-direction: column;
  width: clamp(560px, 46vw, 820px);
  max-width: 100%;
  height: 100%;
  min-width: 0;
  background: var(--bg-2);
  border-left: 1px solid var(--line-strong);
  box-shadow: -18px 0 46px rgba(0, 0, 0, .18);
}

@media (min-width: 900px) {
  .ai-drawer {
    margin: 12px;
    height: calc(100% - 24px);
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-xl);
    overflow: hidden;
  }
}

.ai-slide-enter-active, .ai-slide-leave-active { transition: opacity var(--dur) var(--ease); }
.ai-slide-enter-active .ai-drawer, .ai-slide-leave-active .ai-drawer { transition: transform var(--dur-lg) var(--ease-out); }
.ai-slide-enter-from, .ai-slide-leave-to { opacity: 0; }
.ai-slide-enter-from .ai-drawer, .ai-slide-leave-to .ai-drawer { transform: translateX(12px); }

/* ===== 头部 ===== */
.ai-head {
  flex: none;
  display: flex; align-items: center; gap: 11px;
  padding: 12px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.ai-mark {
  flex: none;
  display: grid; place-items: center;
  width: 32px; height: 32px;
  border-radius: var(--radius-sm);
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
}
.ai-mark img { width: 18px; height: auto; }
.ai-head-text { min-width: 0; line-height: 1.3; }
.ai-head-text strong {
  display: block;
  font-size: 14px; font-weight: 650; color: var(--text);
}
.ai-head-sub {
  display: block;
  margin-top: 2px;
  font-size: 11px; color: var(--text-4);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ai-head-acts { margin-left: auto; display: flex; gap: 2px; flex: none; }
.ai-icon-btn {
  width: 30px; height: 30px;
  display: grid; place-items: center;
  border: 1px solid transparent; border-radius: var(--radius-sm);
  background: transparent; color: var(--text-3);
  cursor: pointer;
  transition: background-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.ai-icon-btn:hover { background: var(--surface-3); color: var(--text); }
.ai-icon-btn :deep(svg) { width: 15px; height: 15px; }
.ai-icon-btn:focus-visible { outline: 2px solid var(--ds); outline-offset: 1px; }

/* ===== 阶段 ===== */
.ai-steps {
  flex: none;
  display: flex; align-items: center; gap: 8px;
  padding: 9px 16px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--text-4);
  overflow: hidden;
}
.ai-step { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.ai-step i {
  width: 16px; height: 16px;
  display: grid; place-items: center;
  border-radius: 50%;
  border: 1px solid var(--line-2);
  font-style: normal; font-size: 9.5px;
  color: var(--text-4);
}
.ai-step.on { color: var(--text); font-weight: 600; }
.ai-step.on i { border-color: var(--ds); background: var(--ds); color: #fff; }
.ai-step.done i { border-color: var(--ds-line); background: var(--ds-soft); color: var(--ds); }
.ai-step-line { flex: 1; min-width: 8px; height: 1px; background: var(--line); }
.ai-step-line.done { background: var(--ds-line); }

/* ===== 主体 ===== */
.ai-body {
  flex: 1; min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}


.ai-block { padding: 18px 18px 0; }
.ai-block:last-of-type { padding-bottom: 4px; }
.ai-block-title {
  margin: 0 0 8px;
  font-size: 12px; font-weight: 650;
  color: var(--text-2);
  letter-spacing: .01em;
}
.ai-block-desc { margin: -2px 0 10px; font-size: 11.5px; color: var(--text-4); line-height: 1.6; }

.ai-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.ai-facts div { padding: 9px 11px; background: var(--surface); }
.ai-facts dt { font-size: 10.5px; color: var(--text-4); }
.ai-facts dd {
  margin: 3px 0 0;
  font-family: var(--font-data);
  font-size: 15px; font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.ai-facts dd.critical { color: var(--critical); }
.ai-facts dd.warning { color: var(--warning); }

.ai-prompts {
  margin: 0; padding: 0;
  list-style: none;
  display: flex; flex-direction: column; gap: 6px;
}
.ai-prompts li {
  position: relative;
  padding: 8px 11px 8px 26px;
  font-size: 12px; color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.ai-prompts li::before {
  content: '?';
  position: absolute; left: 10px; top: 8px;
  font-size: 11px; font-weight: 700;
  color: var(--ds);
}

.ai-run {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
  padding: 18px;
  margin-top: 4px;
}
.ai-run .btn.primary.lg { min-width: 150px; }

/* ===== 配置 ===== */
.ai-config { padding: 16px 18px 24px; max-width: 620px; }
.ai-note {
  display: flex; gap: 10px;
  padding: 11px 13px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-left: 2px solid var(--ds);
  border-radius: var(--radius-sm);
  margin-bottom: 18px;
}
.ai-note-icon { color: var(--ds); flex: none; }
.ai-note-icon :deep(svg) { width: 15px; height: 15px; }
.ai-note strong { display: block; font-size: 12px; color: var(--text-2); margin-bottom: 3px; }
.ai-note p { margin: 0; font-size: 11.5px; line-height: 1.7; color: var(--text-4); }

.ai-field { margin-bottom: 14px; }
.ai-field label {
  display: block;
  margin-bottom: 5px;
  font-size: 11.5px; color: var(--text-3);
}
.ai-field .inp { width: 100%; }
.ai-hint { margin: 5px 0 0; font-size: 11px; color: var(--text-4); line-height: 1.6; }

.ai-msg { margin: 12px 0 0; font-size: 12px; color: var(--critical); }
.ai-msg.bad { color: var(--critical); }
.ai-msg.ok { color: var(--ok); }
.ai-config-acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }

/* 会诊里的主操作统一用 AI 蓝，避免和"故障红"混淆 */
.ai-drawer .btn.primary {
  background: var(--ds-dk);
  border-color: var(--ds-dk);
  color: #fff;
}
.ai-drawer .btn.primary:hover:not(:disabled) {
  background: var(--ds);
  border-color: var(--ds);
}

/* ===== 运行中 ===== */
.ai-running {
  display: flex; align-items: center; gap: 10px;
  margin: 18px;
  padding: 12px 14px;
  font-size: 12.5px; color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-left: 2px solid var(--ds);
  border-radius: var(--radius-sm);
}
.ai-dots { display: inline-flex; gap: 3px; }
.ai-dots i {
  width: 4px; height: 4px; border-radius: 50%;
  background: var(--ds);
  animation: ai-dot 1.2s ease-in-out infinite;
}
.ai-dots i:nth-child(2) { animation-delay: .15s }
.ai-dots i:nth-child(3) { animation-delay: .3s }
@keyframes ai-dot { 0%, 60%, 100% { opacity: .25 } 30% { opacity: 1 } }


/* ===== 报告 ===== */
.ai-report {
  margin: 16px 18px 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
}
.ai-report-head {
  display: flex; flex-wrap: wrap; align-items: flex-start; gap: 8px 12px;
  padding: 12px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
}
.arh-text { min-width: 0; }
.arh-text h3 { margin: 0; font-size: 13px; font-weight: 650; color: var(--text); }
.arh-text p {
  margin: 3px 0 0;
  font-size: 11px; color: var(--text-4);
  font-family: var(--font-data);
}
.arh-acts { margin-left: auto; display: flex; flex-wrap: wrap; gap: 5px; }

.ai-md {
  padding: 14px 16px 16px;
  font-size: 12.5px; line-height: 1.82;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
/* renderMd 把 ## 映射成 h3、# 映射成 h2，两个层级都要带强调条 */
.ai-md :deep(h2),
.ai-md :deep(h3) {
  font-size: 13px; font-weight: 650; color: var(--text);
  margin: 18px 0 8px; padding-left: 9px;
  border-left: 3px solid var(--ds);
  line-height: 1.5;
}
.ai-md :deep(h2:first-child),
.ai-md :deep(h3:first-child) { margin-top: 0; }
.ai-md :deep(h4) { font-size: 12.5px; font-weight: 620; color: var(--text); margin: 14px 0 6px; }
.ai-md :deep(p) { margin: 7px 0; }
.ai-md :deep(ul), .ai-md :deep(ol) { margin: 7px 0 7px 18px; padding: 0; }
.ai-md :deep(li) { margin: 3px 0; }
.ai-md :deep(strong) { color: var(--text); font-weight: 600; }
.ai-md :deep(code) {
  padding: 1px 5px;
  background: var(--surface-3);
  border-radius: var(--radius-xs);
  font-family: var(--font-mono); font-size: 11px;
  color: var(--text);
}
.ai-md :deep(pre) {
  margin: 9px 0; padding: 10px 12px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: auto;
}
.ai-md :deep(pre code) { background: none; padding: 0; font-size: 11px; }
.ai-md :deep(blockquote) {
  margin: 9px 0; padding: 6px 12px;
  border-left: 2px solid var(--line-strong);
  color: var(--text-3);
}
.ai-md :deep(hr) { border: 0; border-top: 1px solid var(--line); margin: 14px 0; }
.ai-md :deep(table) {
  width: 100%; margin: 10px 0;
  border-collapse: collapse;
  font-size: 11.5px;
}
.ai-md :deep(th) {
  padding: 6px 9px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  text-align: left; font-weight: 600; color: var(--text-3);
}
.ai-md :deep(td) { padding: 6px 9px; border: 1px solid var(--line); }

/* ===== 对话 ===== */
.ai-thread {
  margin: 16px 18px 0;
  padding-bottom: 4px;
  border-top: 1px solid var(--line);
}
.ai-thread-title {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  margin: 14px 0 10px;
  font-size: 12px; font-weight: 650; color: var(--text-2);
}
.ai-thread-hint { font-size: 11px; font-weight: 400; color: var(--text-4); }

.ai-msg-row { display: flex; gap: 9px; margin-bottom: 12px; align-items: flex-start; }
.ai-msg-row.user { flex-direction: row-reverse; }
.ai-avatar {
  flex: none;
  width: 24px; height: 24px;
  display: grid; place-items: center;
  border-radius: var(--radius-sm);
  font-size: 10.5px; font-weight: 600;
}
.ai-avatar.assistant { background: var(--ds-soft); border: 1px solid var(--ds-line); }
.ai-avatar.assistant img { width: 13px; height: auto; }
.ai-avatar.user { background: var(--surface-3); border: 1px solid var(--line-2); color: var(--text-3); }

.ai-bubble {
  min-width: 0;
  max-width: min(88%, 62ch);
  padding: 9px 12px;
  font-size: 12.5px; line-height: 1.7;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.ai-msg-row.assistant .ai-bubble { border-left: 2px solid var(--ds-line); }
.ai-msg-row.user .ai-bubble { background: var(--surface); }
.ai-bubble.failed { border-color: var(--critical); }
.ai-bubble .ai-md { padding: 0; font-size: 12.5px; line-height: 1.7; }
.ai-user-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.ai-caret {
  display: inline-block;
  width: 2px; height: 12px;
  margin-left: 2px; vertical-align: -1px;
  background: var(--ds);
  animation: ai-blink 1s step-end infinite;
}
@keyframes ai-blink { 50% { opacity: 0 } }
.ai-retry { margin-top: 6px; }

.ai-followups {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin-top: 4px; padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.ai-followups > span { font-size: 11px; color: var(--text-4); }
.ai-followups button {
  padding: 5px 9px;
  font: inherit; font-size: 11.5px;
  color: var(--text-2);
  background: var(--surface);
  border: 1px solid var(--line-2);
  border-radius: 99px;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.ai-followups button:hover { border-color: var(--ds); color: var(--ds); }

/* ===== 输入 ===== */
.ai-composer {
  flex: none;
  padding: 10px 16px 12px;
  background: var(--surface);
  border-top: 1px solid var(--line);
}
.ai-input {
  display: flex; align-items: flex-end; gap: 8px;
  padding: 6px 6px 6px 10px;
  background: var(--bg-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ai-input:focus-within { border-color: var(--ds); box-shadow: 0 0 0 3px var(--ds-soft); }
.ai-input textarea {
  flex: 1; min-width: 0;
  max-height: 132px;
  padding: 5px 0;
  border: 0; background: transparent;
  color: var(--text);
  font: inherit; font-size: 12.5px; line-height: 1.6;
  resize: none;
  outline: none;
}
.ai-input textarea::placeholder { color: var(--text-4); }
.ai-send {
  flex: none;
  width: 32px; height: 32px;
  display: grid; place-items: center;
  border: 1px solid var(--ds-dk); border-radius: var(--radius-sm);
  background: var(--ds-dk); color: #fff;
  cursor: pointer;
  transition: background-color var(--dur) var(--ease);
}
.ai-send:hover:not(:disabled) { background: var(--ds); }
.ai-send:disabled { opacity: .38; cursor: not-allowed; }
.ai-send :deep(svg) { width: 14px; height: 14px; }
.ai-composer-hint {
  display: flex; flex-wrap: wrap; gap: 4px 12px;
  margin: 7px 0 0;
  font-size: 10.5px; color: var(--text-4);
}
.ai-composer-warn { margin-left: auto; }

@media (max-width: 620px) {
  .ai-drawer { width: 100%; }
  .ai-steps { padding-inline: 12px; }
  .ai-block, .ai-config { padding-inline: 14px; }
  .ai-report, .ai-thread { margin-inline: 14px; }
  .ai-composer { padding-inline: 12px; }
  .ai-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .ai-report-head { flex-direction: column; gap: 9px; }
  .arh-acts { margin-left: 0; width: 100%; }
  .ai-md { padding: 12px 13px 14px; }
  .ai-composer-warn { margin-left: 0; }
}
 .ai-head { border-top:2px solid var(--brand); }
.ai-step.on i { background:var(--status-ai); border-color:var(--status-ai); color:var(--bg); }
.ai-focus-note { color:var(--ds-lt); font-size:12px; margin:4px 0; }

@media (min-width:1000px) {
  .ai-drawer { width:clamp(680px,56vw,850px); }
  .consult-grid { display:grid; grid-template-columns:minmax(170px,32%) minmax(0,1fr); align-items:start; padding:16px; gap:14px; }
  .consult-grid .ai-block { padding:14px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); }
  .consult-grid .consult-roles { grid-column:1; grid-row:1 / span 3; background:var(--surface-2); }
  .consult-grid .ai-run { margin:0; padding:0; flex-wrap:wrap; }
  .consult-grid .ai-facts { grid-template-columns:repeat(3,minmax(0,1fr)); }
}

.ai-head { padding:16px 20px; background:linear-gradient(110deg,var(--ds-soft),var(--surface) 72%); border-top-color:var(--ds); }
.ai-run > .btn.primary { color:#fff; background:var(--ds-dk); border-color:var(--ds-dk); }
.ai-run > .btn.primary:hover { filter:brightness(1.12); }
.ai-mark, .perspective-logo { background:var(--ds-soft); }
.ai-head-text strong { font-size:18px; letter-spacing:-.025em; }
.ai-mark { width:40px; height:40px; border-radius:12px; background:var(--surface); }
.ai-mark img { width:26px; }
.consult-grid .perspective { overflow:hidden; padding:0; }
.perspective-head { display:flex; align-items:center; gap:12px; padding:16px; background:linear-gradient(105deg,var(--ds-soft),var(--surface)); border-bottom:1px solid var(--line); }
.perspective-logo { display:grid; place-items:center; width:44px; height:44px; background:var(--surface); border:1px solid var(--ds-line); border-radius:12px; }
.perspective-head small { font-size:11px; color:var(--text-3); }
.perspective-head h3 { margin:3px 0 0; font-size:20px; color:var(--text); }
.perspective-body { padding:14px 16px; }
.perspective-body h4 { font-size:12px; color:var(--text-3); margin:0 0 8px; }
.perspective-body ul { padding-left:18px; list-style:disc; margin:0; }
.perspective-body li { padding:3px 0; font-size:13px; color:var(--text); }
.perspective-body li::marker { color:var(--brand-lt); }
.ai-run .btn svg { width:15px; }
.ai-composer .ai-send { display:inline-flex; align-items:center; justify-content:center; gap:5px; width:auto; padding:0 12px; font:inherit; font-weight:600; }
.ai-composer .ai-send:enabled,.ai-run .btn.primary { background:var(--brand); color:white; }
@media(min-width:1000px){.consult-grid .consult-roles { background:var(--surface); padding:12px 8px; }.consult-roles .ai-block-title { padding:4px 8px; }}
@media(max-width:999px){.consult-grid .perspective { margin:16px 16px 0; border:1px solid var(--line); border-radius:var(--radius); }}
@media(prefers-reduced-motion:no-preference){.perspective-body { animation:perspective-in var(--dur-lg) var(--ease-out); } @keyframes perspective-in { from {opacity:.4; transform:translateY(4px)} to {opacity:1; transform:translateY(0)} }}
</style>

