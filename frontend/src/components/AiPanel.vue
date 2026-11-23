<script setup>
/**
 * DeepSeek 智能分析面板
 *
 * 视觉：中国铁塔红（品牌）+ DeepSeek 蓝（AI）双色融合
 * 行为：
 *   1. 先展示本次分析的关键事实（让用户知道 AI 看到了什么）
 *   2. 深度思考动画 → 流式报告
 *   3. 报告后可直接追问
 */
import { ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import { api } from '../api/client'
import AiContextPreview from './AiContextPreview.vue'
import InterfaceState from './InterfaceState.vue'
import { feedback } from '../stores/interface'
import { useTaskStore } from '../stores/task'
import { renderMd } from '../utils/markdown'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['update:open'])

const store = useTaskStore()

const tab = ref('report')
const drawerRef = ref(null)
let previousFocus = null
const report = ref('')
const previewOpen = ref(false)
const reportContextHash = ref('')
let reportController = null
let chatController = null
onUnmounted(() => { reportController?.abort(); chatController?.abort() })
const running = ref(false)
const thinkOpen = ref(true)
const thinkDone = ref(false)
const thinkTitle = ref('')
const steps = ref([])
const elapsed = ref(0)
const err = ref('')

const chat = ref([])
const question = ref('')
const chatBusy = ref(false)
const chatBox = ref(null)
const questionInput = ref(null)
const streamLabels = { followup: '正在生成追问回复…', analysis: '正在生成分析报告…' }
const expert = ref('general')
const profiles = {
  general: ['综合研判', '串联信令与媒体证据', ['第一处异常出现在哪里？', '哪些结论仍需补抓验证？']],
  sip: ['信令事务', '追踪请求、响应与重传', ['哪个事务缺少最终响应？', '重传与明确拒绝如何区分？']],
  media: ['媒体链路', '核对 SSRC、丢包与画面', ['协商和实际 SSRC 是否一致？', '画面重建失败有哪些可验证原因？']],
  field: ['现场排障', '制定两端复核步骤', ['平台侧先检查什么？', '下一次应在哪一端抓包？']]
}
const suggestedQuestions = computed(() => profiles[expert.value][2])

function useSuggestion(text) {
  question.value = text
  nextTick(() => questionInput.value?.focus())
}

const cfg = ref({ has_key: false, key_hint: '', model: '', base_url: '' })
const keyInput = ref('')
const modelInput = ref('')
const baseInput = ref('')
const cfgMsg = ref('')
const cfgBusy = ref(false)
const testing = ref(false)

const PLAN = ['等待模型响应', '接收分析结果']

const canAnalyze = computed(() =>
  store.task && store.task.status === 'completed')

/* ---- 分析事实摘要（让用户知道 AI 的依据） ---- */
const facts = computed(() => {
  const s = store.task?.summary || {}
  const d = s.diagnostics || {}
  return [
    { k: '报文', v: (s.packet_count || 0).toLocaleString() },
    { k: '会话', v: s.session_count ?? 0 },
    { k: '信令成功', v: s.signal_success_rate != null
        ? s.signal_success_rate.toFixed(1) + '%' : '—',
      cls: s.signal_success_rate >= 90 ? 'ok' : 'warning' },
    { k: '有媒体', v: s.sessions_with_media ?? 0,
      cls: s.sessions_with_media ? 'ok' : 'critical' },
    { k: '严重', v: d.critical || 0, cls: d.critical ? 'critical' : '' },
    { k: '警告', v: d.warning || 0, cls: d.warning ? 'warning' : '' }
  ]
})

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

async function loadCfg() {
  try {
    cfg.value = await api.aiConfig()
    modelInput.value = cfg.value.model || ''
    baseInput.value = cfg.value.base_url || ''
    if (cfg.value.has_key && tab.value === 'config') tab.value = 'report'
  } catch { /* 忽略 */ }
}

async function saveCfg() {
  cfgBusy.value = true
  cfgMsg.value = ''
  try {
    const body = {}
    if (keyInput.value.trim()) body.api_key = keyInput.value.trim()
    if (modelInput.value.trim()) body.model = modelInput.value.trim()
    if (baseInput.value.trim()) body.base_url = baseInput.value.trim()
    cfg.value = await api.aiSaveConfig(body)
    keyInput.value = ''
    cfgMsg.value = '已保存'
    if (cfg.value.has_key) tab.value = 'report'
  } catch (e) {
    cfgMsg.value = '保存失败：' + e.message
  } finally {
    cfgBusy.value = false
  }
}

async function testConn() {
  testing.value = true
  cfgMsg.value = ''
  try {
    const r = await api.aiTest()
    cfgMsg.value = '连接正常：' + (r.reply || 'OK')
  } catch (e) {
    cfgMsg.value = '连接失败：' + e.message
  } finally {
    testing.value = false
  }
}

/* ---- 思考动画 ---- */
function startThinking() {
  thinkOpen.value = true
  thinkDone.value = false
  thinkTitle.value = '等待模型响应'
  steps.value = PLAN.map(t => ({ text: t, state: 'wait', time: '' }))
  steps.value[0].state = 'active'
  elapsed.value = 0
  const t0 = Date.now()
  const timer = setInterval(() => { elapsed.value = ((Date.now() - t0) / 1000).toFixed(1) }, 200)
  return {
    toReport() {
      steps.value[0].state = 'done'
      steps.value[1].state = 'active'
      thinkTitle.value = '正在接收结果'
    },
    finish() {
      clearInterval(timer)
      steps.value.forEach(s => { s.state = 'done' })
      thinkDone.value = true
      thinkOpen.value = false
      thinkTitle.value = '分析完成'
    },
    fail() {
      clearInterval(timer)
      thinkDone.value = true
      thinkTitle.value = '分析中断'
    }
  }
}

/* ---- 报告 ---- */
async function runAnalyze(contextHash) {
  previewOpen.value = false
  if (running.value || !canAnalyze.value) return
  if (!cfg.value.has_key) { tab.value = 'config'; return }

  running.value = true
  err.value = ''
  report.value = ''
  reportContextHash.value = ''
  chat.value = []
  const think = startThinking()
  reportController = new AbortController()

  try {
    const res = await fetch(`/api/v1/ai/analyze/${store.currentTaskId}`, {
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
    let buf = '', acc = '', first = true, completed = false

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
          if (first) { first = false; think.toReport() }
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
    think.finish()
    feedback('success')
  } catch (e) {
    report.value = ''
    err.value = e.message
    think.fail()
    if (e.name !== 'AbortError') feedback('error')
  } finally {
    running.value = false
    reportController = null
  }
}

/* ---- 追问 ---- */
function composerKeydown(event) {
  if (event.isComposing || event.keyCode === 229 || event.shiftKey) return
  event.preventDefault()
  sendQuestion()
}

async function sendQuestion() {
  const q = question.value.trim()
  if (!q || chatBusy.value || running.value || !reportContextHash.value || !store.currentTaskId) return

  feedback('send')
  question.value = ''
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
    const res = await fetch(`/api/v1/ai/chat/${store.currentTaskId}`, {
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
    const el = chatBox.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function exportReport() {
  const url = URL.createObjectURL(new Blob([report.value], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'DeepSeek-分析-' + store.currentTaskId + '.md'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function copyReport() {
  navigator.clipboard?.writeText(report.value)
}

watch(() => props.open, async (v) => {
  if (!v) { previousFocus?.focus?.(); previousFocus = null; return }
  previousFocus = document.activeElement
  await nextTick()
  drawerRef.value?.focus()
  const before = cfg.value.has_key
  await loadCfg()
  if (!cfg.value.has_key) tab.value = 'config'
  else if (!before || !report.value) tab.value = 'report'
})
</script>

<template>
  <Teleport to="body">
    <Transition name="slide">
      <div v-if="open" class="mask" @click.self="close">
        <aside ref="drawerRef" class="drawer glass-panel" role="dialog" aria-modal="true" aria-label="DeepSeek 智能分析" tabindex="-1" @keydown="onDrawerKeydown">
          <!-- 双品牌头部 -->
          <div class="head">
            <div class="head-in">
              <div class="logos"><img src="/brand/analyzer.svg" class="tower-mark" alt="铁塔抓包分析"><span class="brand-join" aria-hidden="true"></span>
                <img src="/brand/deepseek.svg" alt="" class="lg-ds" />
              </div>
              <div class="head-txt">
                <div class="head-name">DeepSeek 专家会诊</div>
                <div class="head-sub">
                  <span class="dot-brand"></span>
                  结合本次抓包分析结果
                  <template v-if="cfg.model"> · <span class="mono">{{ cfg.model }}</span></template>
                </div>
              </div>
              <div class="spacer"></div>
              <button class="hbtn" @click="tab = tab === 'config' ? 'report' : 'config'"
                      :title="tab === 'config' ? '返回' : '设置'">
                <AppIcon :name="tab === 'config' ? 'back' : 'settings'" />
              </button>
              <button class="hbtn" @click="close" title="关闭">
                <AppIcon name="close" />
              </button>
            </div>
          </div>

          <!-- 配置 -->
          <div v-if="tab === 'config'" class="body">
            <div class="cfg-note">
              <div class="cn-title">数据边界</div>
              只发送解析后的<strong>结构化摘要</strong>（会话、流、诊断结论），
              <strong>绝不发送抓包原始字节</strong>。
              Key 仅保存在本机后端，前端只能看到末四位。
            </div>

            <div class="field">
              <label>API Key</label>
              <input v-model="keyInput" type="password" class="inp full"
                     :placeholder="cfg.has_key ? '已配置 ' + cfg.key_hint + '（留空则不修改）' : 'sk-...'" />
            </div>
            <div class="field">
              <label>模型</label>
              <input v-model="modelInput" type="text" class="inp full"
                     placeholder="deepseek-flash" />
              <div class="hint">
                使用当前服务账户已开通的模型 ID。设置完成后可测试连接。
              </div>
            </div>
            <div class="field">
              <label>接口地址</label>
              <input v-model="baseInput" type="text" class="inp full"
                     placeholder="https://api.deepseek.com" />
            </div>

            <div v-if="cfgMsg" class="cfg-msg" :class="{ bad: cfgMsg.includes('失败') }">
              {{ cfgMsg }}
            </div>

            <div class="row mt-20" style="gap:8px">
              <button class="btn primary" @click="saveCfg" :disabled="cfgBusy">
                {{ cfgBusy ? '保存中…' : '保存' }}
              </button>
              <button class="btn" @click="testConn" :disabled="testing || !cfg.has_key">
                {{ testing ? '测试中…' : '测试连接' }}
              </button>
            </div>
          </div>

          <!-- 报告 -->
          <div v-else class="body flush">
            <InterfaceState v-if="!canAnalyze" icon="signal" title="请先完成一次抓包分析"
              detail="会诊将使用当前任务的信令、媒体与规则诊断摘要。" />

            <template v-else>
              <AiContextPreview v-if="previewOpen" :task-id="store.currentTaskId" @cancel="previewOpen = false" @confirm="runAnalyze" />
              <!-- 分析事实（AI 的依据） -->
              <div class="facts">
                <div class="facts-title">本次分析事实</div>
                <div class="facts-grid">
                  <div v-for="f in facts" :key="f.k" class="fact">
                    <i>{{ f.k }}</i>
                    <b :class="f.cls">{{ f.v }}</b>
                  </div>
                </div>
              </div>

              <!-- 起始 -->
              <div v-if="!report && !running" class="start">
                <header class="consult-title"><img src="/brand/deepseek.svg" alt="" /><h3>选择会诊专家</h3></header>
                <div class="expert-list">
                  <button v-for="(profile,key) in profiles" :key="key" type="button" :aria-pressed="expert === key" @click="expert = key">
                    <span><strong>{{ profile[0] }}</strong><small>{{ profile[1] }}</small></span>
                    <span aria-hidden="true">{{ expert === key ? '✓' : '○' }}</span>
                  </button>
                </div>
                <section class="focus-preview" aria-live="polite"><strong>本次分析重点</strong>
                  <ul><li v-for="item in suggestedQuestions" :key="item">{{ item }}</li></ul>
                </section>
                <button class="btn primary lg" @click="previewOpen = true"
                        :disabled="running || !cfg.has_key">
                  <img src="/brand/deepseek-white.svg" alt="" class="btn-ico" />
                  查看发送内容
                </button>
                <div v-if="!cfg.has_key" class="hint mt-10">需要先配置 API Key</div>
              </div>

              <!-- 思考过程 -->
              <div v-if="steps.length" class="think" :class="{ done: thinkDone }">
                <button type="button" class="think-head" :aria-expanded="thinkOpen" @click="thinkOpen = !thinkOpen">
                  <img src="/brand/deepseek.svg" alt="" class="whale" />
                  <span class="t-title">{{ thinkTitle }}</span>
                  <span v-if="!thinkDone" class="t-dots"><i></i><i></i><i></i></span>
                  <span class="spacer"></span>
                  <span class="t-time mono">{{ elapsed }}s</span>
                  <span class="t-arrow" :class="{ open: thinkOpen }"><AppIcon name="next" /></span>
                </button>
                <div v-show="thinkOpen" class="t-steps">
                  <div v-for="(s, i) in steps" :key="i" class="tstep" :class="s.state">
                    <span class="sdot"></span>
                    <span class="stxt">{{ s.text }}</span>
                    <span class="stime mono">{{ s.time }}</span>
                  </div>
                </div>
              </div>

              <p v-if="running || chatBusy" role="status" class="stream-state">{{ chatBusy ? streamLabels.followup : streamLabels.analysis }}</p>
              <!-- 报告 -->
              <div v-if="report" class="report">
                <div class="r-tools"><strong class="signature">{{ profiles[expert][0] }} · 研判报告</strong>
                  <button class="btn-mini" :disabled="running || chatBusy" @click="report = ''; chat = []; steps = []; question = ''; reportContextHash = ''">新会诊</button>
                  <button class="btn-mini" @click="copyReport">复制</button><button class="btn-mini" @click="exportReport">导出 .md</button>
                  <button class="btn-mini" @click="previewOpen = true" :disabled="running">
                    重新分析
                  </button>
                </div>
                <div class="md" v-html="renderMd(report)"></div>
              </div>

              <div v-if="err" class="err-box" style="margin:12px 14px">{{ err }}</div>

              <!-- 对话 -->
              <div v-if="report" class="chat">
                <div class="chat-log" ref="chatBox" aria-label="会诊对话" :aria-busy="chatBusy">
                  <div v-for="(m, i) in chat" :key="i" class="cmsg" :class="m.role">
                    <div class="cav" :class="m.role">
                      <img v-if="m.role === 'assistant'" src="/brand/deepseek.svg" alt="" />
                      <span v-else>我</span>
                    </div>
                    <div class="message-content">
                      <div class="message-byline">{{ m.role === 'assistant' ? 'DeepSeek' : '你' }}</div>
                      <div class="cbub" :class="{ streaming: m.streaming, 'message-failed': m.failed }">
                        <div v-if="m.role === 'assistant'" v-html="renderMd(m.content)"></div>
                        <div v-else>{{ m.content }}</div>
                      </div>
                      <button v-if="m.role === 'user' && m.failed && !chatBusy" type="button" class="btn-mini"
                        @click="useSuggestion(m.content)">填回输入框</button>
                    </div>
                  </div>
                </div>
                <div class="chat-prompts" v-if="!chatBusy && reportContextHash && !running">
                  <span>继续探索</span>
                  <div class="prompt-list">
                    <button v-for="prompt in suggestedQuestions" :key="prompt" @click="useSuggestion(prompt)">{{ prompt }} <span aria-hidden="true"><AppIcon name="open" /></span></button>
                  </div>
                </div>
                <div class="chat-in">
                  <textarea ref="questionInput" v-model="question" rows="1" aria-label="输入追问"
                            :disabled="running || !reportContextHash"
                            placeholder="继续追问，例如：这个 SSRC 要去哪里改？"
                            @keydown.enter="composerKeydown"></textarea>
                  <button class="send" @click="sendQuestion" aria-label="发送追问"
                          :disabled="chatBusy || running || !reportContextHash || !question.trim()">
                    <AppIcon name="send" />
                  </button>
                </div>
                <div class="chat-hint">Enter 发送 · Shift + Enter 换行 · 请勿输入敏感信息</div>
              </div>
            </template>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0; z-index: 300;
  background:color-mix(in srgb,var(--bg) 26%,transparent);
  backdrop-filter:blur(14px) saturate(.85);
  display: flex; justify-content: flex-end;
}
.drawer {
  width:clamp(580px,44vw,880px); min-width:0; max-width:100%; height:100%;
  background: var(--bg-2);
  border-left: 1px solid var(--line-strong);
  display: flex; flex-direction: column;
  box-shadow: -12px 0 40px rgba(0, 0, 0, .35);
}

.slide-enter-active, .slide-leave-active { transition: opacity .2s; }
.slide-enter-active .drawer, .slide-leave-active .drawer {
  transition: transform .28s var(--ease);
}
.slide-enter-from, .slide-leave-to { opacity: 0; }
.slide-enter-from .drawer, .slide-leave-to .drawer {
  transform: translateX(100%);
}

/* ===== 头部 ===== */
.head {
  position: relative;
  flex: none;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  box-shadow: inset 0 2px 0 var(--ds);
}
.head-in {
  position: relative;
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px;
}
.logos { display:flex; align-items:center;gap:7px }
.tower-mark {width:38px;height:38px}.brand-join {width:16px;height:1px;background:linear-gradient(90deg,var(--brand),var(--ds))}
.head-in { background:linear-gradient(115deg,var(--ds-soft),transparent 75%); }
@supports (backdrop-filter:blur(1px)) {
  .drawer.glass-panel {
    background:color-mix(in srgb,var(--bg-2) 77%,transparent);
    backdrop-filter:blur(24px) saturate(115%);
  }
}
@media (min-width:851px) {
  .drawer.glass-panel {
    margin:12px; height:calc(100% - 24px); overflow:hidden;
    border:1px solid var(--line-strong); border-radius:16px;
    box-shadow:0 12px 42px rgb(0 0 0 / 18%);
  }
}
@media (max-width:850px) { .drawer { width:min(100%,640px); } }
@media (max-width:480px) {
  .head-in { gap:8px; padding-inline:12px; }
  .logos .tower-mark { width:28px; height:28px; }
  .brand-join { display:none; }
  .head-txt { min-width:0; }
  .head-sub { overflow-wrap:anywhere; }
}

.lg-ds { height: 20px; width: auto; }
.head-txt { line-height: 1.35; min-width: 0; }
.head-name {
  font-size: 18px; font-weight: 600;
  color: var(--text); letter-spacing: -.1px;
}
.head-sub {
  font-size: 10.5px; color: var(--text-4);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dot-brand {
  display: inline-block;
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--ds); opacity: .9; vertical-align: middle; margin-right: 4px;
}
.hbtn {
  width: 28px; height: 28px;
  border-radius: 5px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-3); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: .15s;
  flex: none;
}
.hbtn:hover { background: var(--surface-3); border-color: var(--line); color: var(--text); }
.hbtn svg { width: 14px; height: 14px; }

.body { flex: 1; overflow-y: auto; padding: 16px; }
.body.flush { padding: 0; display: flex; flex-direction: column; }

/* 配置 */
.cfg-note {
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ds);
  border-radius: var(--radius-sm);
  padding: 13px 15px;
  font-size: 12px; color: var(--text-3);
  line-height: 1.8; margin-bottom: 18px;
}
.cn-title {
  font-size: 11.5px; font-weight: 600;
  color: var(--ds-lt); margin-bottom: 5px;
}
.cfg-note strong { color: var(--text-2); }

.field { margin-bottom: 15px; }
.field label {
  display: block; font-size: 11.5px;
  color: var(--text-3); margin-bottom: 6px;
}
.inp.full { width: 100%; }
.hint { font-size: 10.5px; color: var(--text-4); margin-top: 5px; line-height: 1.6; }
.cfg-msg { font-size: 12px; color: var(--ok); margin-top: 10px; }
.cfg-msg.bad { color: var(--critical); }

/* 事实摘要 */
.facts {
  padding: 14px 16px 0;
}
.facts-title {
  font-size: 11px; color: var(--text-4);
  margin-bottom: 6px;
}
.facts-grid {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 11px 8px;
}
.fact { text-align: center; }
.fact i {
  display: block; font-size: 11px;
  color: var(--text-4); font-style: normal;
  margin-bottom: 2px;
}
.fact b {
  font-size: 14px; font-weight: 650;
  color: var(--text); font-variant-numeric: tabular-nums;
}
.fact b.ok { color: var(--ok); }
.fact b.warning { color: var(--warning); }
.fact b.critical { color: var(--critical); }

/* 起始 */
.start { padding: 40px 26px 26px; text-align: center; }
.drawer .btn.primary { background: var(--ds-dk); border-color: var(--ds-dk); color: #fff; }
.drawer .btn.primary:hover:not(:disabled) { background: var(--ds); border-color: var(--ds); }
.start-icon {
  width: 56px; height: 56px; margin: 0 auto 16px;
  border-radius: 15px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  display: flex; align-items: center; justify-content: center;
}
.start-icon img { width: 28px; height: auto; }
.start-title {
  font-size: 15px; font-weight: 650;
  margin-bottom: 8px;
}
.start-desc {
  font-size: 12px; color: var(--text-3);
  line-height: 1.78; margin-bottom: 20px;
  max-width: 380px; margin-left: auto; margin-right: auto;
}
.btn-ico { height: 15px; width: auto; }

/* 思考 */
.think {
  margin: 14px 16px 0;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.think-head {
  width:100%; background:transparent; color:inherit; border:0; text-align:left;
  display: flex; align-items: center; gap: 9px;
  padding: 11px 14px; cursor: pointer;
}
.whale {
  width: 18px; height: 14px; flex: none;
  animation: whaleFloat 2.2s ease-in-out infinite;
}
@keyframes whaleFloat {
  0%, 100% { transform: translateY(0) }
  50% { transform: translateY(-3px) }
}
.think.done .whale { animation: none; }
.t-title {
  font-size: 12.5px; font-weight: 600;
  color: var(--ds-lt);
}
.t-dots { display: inline-flex; gap: 3px; }
.t-dots i {
  width: 3.5px; height: 3.5px; border-radius: 50%;
  background: var(--ds-lt);
  animation: dotPulse 1.3s ease-in-out infinite;
}
.t-dots i:nth-child(2) { animation-delay: .17s }
.t-dots i:nth-child(3) { animation-delay: .34s }
@keyframes dotPulse {
  0%, 60%, 100% { opacity: .28 }
  30% { opacity: 1 }
}
.t-time { font-size: 10px; color: var(--text-4); }
.t-arrow {
  color: var(--text-4); font-size: 15px;
  transition: transform .2s;
}
.t-arrow.open { transform: rotate(90deg); }

.t-steps { padding: 0 14px 12px; }
.tstep {
  display: flex; align-items: center; gap: 10px;
  padding: 5px 0; font-size: 12px;
  color: var(--text-4);
  transition: color .2s;
}
.sdot {
  width: 12px; height: 12px; border-radius: 50%;
  border: 1.5px solid var(--line-strong);
  flex: none; position: relative;
}
.tstep.active { color: var(--text-2); }
.tstep.active .sdot {
  border-color: var(--ds);
  animation: dotPulse 1.4s ease-in-out infinite;
}
.tstep.done { color: var(--text-2); }
.tstep.done .sdot { background: var(--ds); border-color: var(--ds); }
.tstep.done .sdot::after {
  content: ''; position: absolute; left: 3.5px; top: 1px;
  width: 4px; height: 6.5px;
  border: solid #fff; border-width: 0 1.5px 1.5px 0;
  transform: rotate(45deg);
}
.stxt { flex: 1; }
.stime { font-size: 9.5px; color: var(--text-4); }

/* 报告 */
.report { margin:16px 12px 8px; padding:16px; border-radius:12px; background:var(--surface);border:1px solid var(--ds-line);box-shadow:0 2px 12px rgb(0 0 0 / 4%); }
.report :deep(h2) {padding-block:8px;border-bottom:1px solid var(--line);}
.r-tools {
  display: flex; gap: 6px; justify-content: flex-end;
  margin-bottom: 12px;
}
.md {
  font-size: 12.5px; line-height: 1.82;
  color: var(--text-2);
}
.md :deep(h2) {
  font-size: 14px; color: var(--text); font-weight: 650;
  margin: 18px 0 9px; padding-left: 10px;
  border-left: 3px solid var(--ds);
}
.md :deep(h3) {
  font-size: 13px; color: var(--text);
  font-weight: 620; margin: 14px 0 7px;
}
.md :deep(p) { margin: 8px 0; }
.md :deep(ul), .md :deep(ol) { margin: 8px 0 8px 20px; }
.md :deep(li) { margin: 4px 0; }
.md :deep(strong) { color: var(--text); font-weight: 600; }
.md :deep(code) {
  background: var(--surface-3);
  padding: 1.5px 6px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 11px;
  color: var(--warning);
}
.md :deep(table) {
  width: 100%; border-collapse: collapse;
  margin: 10px 0; font-size: 11.5px;
}
.md :deep(th) {
  background: var(--surface-2); padding: 7px 10px;
  border: 1px solid var(--line); text-align: left;
  font-weight: 600; color: var(--text-3);
}
.md :deep(td) {
  padding: 7px 10px;
  border: 1px solid var(--line);
}

/* 对话 */
.chat {
  margin-top: auto;
  border-top: 1px solid var(--line);
  background: var(--surface);
  flex: none;
}
.chat-log {
  max-height: min(32dvh, 420px); overflow-y: auto;
  padding: 14px 16px 0;
  display: flex; flex-direction: column; gap: 12px;
}
.chat-log:empty { display: none; }
.chat-prompts { padding: 14px 16px 0; }
.chat-prompts > span { color: var(--text-3); font-size: 11px; font-weight: 600; letter-spacing: .04em; }
.prompt-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
.prompt-list button { padding: 7px 10px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--surface-2); color: var(--text-2); font: inherit; font-size: 11px; cursor: pointer; transition: border-color .18s, color .18s, transform .18s; }
.prompt-list button:hover { border-color: var(--ds); color: var(--ds); transform: translateY(-1px); }
.prompt-list button span { color: var(--ds); margin-left: 3px; }
.chat-hint { padding: 0 16px 13px; color: var(--text-3); font-size: 12px; }
.cmsg { display: flex; gap: 9px; }
.cmsg.user { flex-direction: row-reverse; }
.cav {
  width: 24px; height: 24px; border-radius: 6px;
  flex: none; display: flex; align-items: center; justify-content: center;
  font-size: 10.5px; font-weight: 600;
}
.cav.assistant {
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
}
.cav.assistant img { width: 14px; height: auto; }
.cav.user {
  background: var(--surface-3);
  border: 1px solid var(--line-2);
  color: var(--text-3);
}
.message-content { max-width:min(88%,54ch); min-width:0; }
.message-byline { margin:0 0 5px; color:var(--text-3); font-size:11px; font-weight:650; }
.cmsg.user .message-byline { text-align:right; }
.cbub {
  padding: 9px 13px; border-radius: var(--radius-lg);
  font-size: 13px; line-height: 1.6;
  overflow-wrap:anywhere;
}
.message-content .btn-mini { margin-top:4px; }

.head-name,.start h3 { font-family:var(--font-heading); }
.cmsg.assistant .cbub {
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
  color: var(--text-2);
}
.cmsg.user .cbub {
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  color: var(--text-2);
}
.cmsg .cbub.message-failed { border-color:var(--critical); }
.cbub.streaming::after {
  content: '▊'; color: var(--ds-lt);
  animation: blink 1s step-end infinite;
  margin-left: 2px;
}
@keyframes blink { 50% { opacity: 0 } }
.cbub :deep(p) { margin: 4px 0; }
.cbub :deep(code) {
  background: var(--surface-3);
  padding: 1px 4px; border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 10.5px; color: var(--warning);
}
.cbub :deep(ul) { margin: 5px 0 5px 16px; }

.chat-in {
  display: flex; gap: 9px; align-items: flex-end;
  padding:8px;
  margin:12px 16px 6px;
  background:var(--ui-layer-raised);
  border:1px solid var(--line);
  border-radius:var(--radius-lg);
}
.chat-in:focus-within { border-color:var(--ds); }
.chat-in textarea {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 9px 12px;
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  min-width:0;
  resize: vertical;
  max-height: 110px;
  line-height: 1.6;
  transition: .15s;
}
.chat-in textarea:focus {
  outline: none;
  border-color: var(--ds);
  box-shadow: 0 0 0 3px var(--ds-soft);
}
.chat-in textarea::placeholder { color: var(--text-4); }
.send {
  width: 36px; height: 36px; flex: none;
  border-radius: 10px;
  background: var(--ds);
  border: none; color: #fff;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background-color .15s;
}
.send:hover:not(:disabled) { background: var(--ds-dk); }
.send:disabled { opacity: .4; cursor: not-allowed; }
.send svg { width: 14px; height: 14px; }
.start { text-align:left; padding:clamp(18px,3vw,38px); }
.consult-title {display:flex;align-items:center;gap:12px}
.consult-title img {width:36px}
.consult-title h3 {margin:0}
.expert-list {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:8px;margin:20px 0}
.expert-list button {display:flex;align-items:center;justify-content:space-between;gap:8px;padding:14px;text-align:left;color:var(--text);background:color-mix(in srgb,var(--surface) 68%,transparent);border:1px solid var(--line);border-radius:10px;cursor:pointer}
.expert-list button[aria-pressed=true] {border-color:var(--ds);background:var(--ds-soft)}
.expert-list small {display:block;color:var(--text-2);margin-top:5px}
.focus-preview {border-inline-start:2px solid var(--ds);padding-inline:14px;margin:18px 0;color:var(--text-2)}
.focus-preview ul {padding-left:18px;line-height:1.65;margin:6px 0}
.stream-state {color:var(--ds-lt);font-size:13px;margin:12px 18px}
.signature {margin-right:auto;color:var(--ds-lt)}
@supports (backdrop-filter:blur(1px)) {
  .drawer .report,.drawer .chat {background:color-mix(in srgb,var(--surface) 80%,transparent)}
}
.drawer .chat-in:focus-within {outline:2px solid var(--ds);outline-offset:2px}
.drawer .chat-log {scrollbar-gutter:stable}
</style>
