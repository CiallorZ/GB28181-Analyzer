<script setup>
/**
 * AI 分析概览（瀑布流第 2 节）
 *
 * 位置：分析总览之后、各详情板块之前。
 * 作用：先给一个"AI 读完数据后的判断"，再往下看细节。
 *
 * 三态：
 *   1. 未配置 Key → 引导配置
 *   2. 未分析     → 深度思考按钮
 *   3. 已出结果   → 结论卡 + 关键发现 + 追问入口
 */
import { ref, computed, watch, nextTick } from 'vue'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import { renderMd } from '../utils/markdown'

defineProps({
  open: { type: Boolean, default: false },
  num: { type: [Number, String], default: 2 }
})
defineEmits(['update:open'])

function openPanel() { store.openAiPanel() }

const store = useTaskStore()

const report = ref('')
const running = ref(false)
const thinkOpen = ref(true)
const thinkDone = ref(false)
const thinkTitle = ref('')
const steps = ref([])
const elapsed = ref(0)
const err = ref('')
const hasKey = ref(false)
const keyHint = ref('')
const model = ref('')

const question = ref('')
const chat = ref([])
const chatBusy = ref(false)
const chatBox = ref(null)

const PLAN = ['读取分析结果', '梳理信令与媒体关联', '定位故障卡点', '生成排查报告']

const canAnalyze = computed(() =>
  store.task && store.task.status === 'completed')

// 关键事实（AI 的依据）
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

// 从报告里提取「结论」段落（第一段）
const conclusion = computed(() => {
  if (!report.value) return ''
  const m = report.value.match(/##\s*结论\s*\n+([\s\S]*?)(?=\n##|$)/)
  if (m) return m[1].trim()
  // 没有「结论」标题就取开头
  return report.value.replace(/^#+\s*.+\n/, '').trim().slice(0, 400)
})

// 关键发现（从「证据链」或列表里抽）
const findings = computed(() => {
  if (!report.value) return []
  const out = []
  // 抓取所有列表项里的前几条
  const lines = report.value.split('\n')
  for (const ln of lines) {
    const m = ln.match(/^\s*[-*]\s+\*\*(.+?)\*\*[:：]?\s*(.*)$/)
    if (m && out.length < 4) {
      out.push({ title: m[1].replace(/\*\*/g, ''), desc: m[2].slice(0, 120) })
      continue
    }
    const m2 = ln.match(/^\s*[-*]\s+(.+)$/)
    if (m2 && out.length < 4 && m2[1].length > 12) {
      out.push({ title: '', desc: m2[1].replace(/\*\*/g, '').slice(0, 130) })
    }
  }
  return out
})

async function loadCfg() {
  try {
    const c = await api.aiConfig()
    hasKey.value = c.has_key
    keyHint.value = c.key_hint || ''
    model.value = c.model || ''
  } catch { /* 忽略 */ }
}

/* ---- 思考动画 ---- */
function startThinking() {
  thinkOpen.value = true
  thinkDone.value = false
  thinkTitle.value = '正在深度思考'
  steps.value = PLAN.map(t => ({ text: t, state: 'wait', time: '' }))
  elapsed.value = 0
  const t0 = Date.now()
  let cur = 0
  steps.value[0].state = 'active'

  const timer = setInterval(() => {
    elapsed.value = ((Date.now() - t0) / 1000).toFixed(1)
    if (cur >= 2) return
    steps.value[cur].state = 'done'
    steps.value[cur].time = elapsed.value + 's'
    cur++
    steps.value[cur].state = 'active'
  }, 850)

  return {
    toReport() {
      clearInterval(timer)
      for (let i = 0; i < 3; i++) {
        if (steps.value[i].state !== 'done') {
          steps.value[i].state = 'done'
          steps.value[i].time = elapsed.value + 's'
        }
      }
      steps.value[3].state = 'active'
    },
    finish() {
      clearInterval(timer)
      steps.value.forEach(s => {
        s.state = 'done'
        if (!s.time) s.time = elapsed.value + 's'
      })
      thinkDone.value = true
      thinkTitle.value = '深度思考完成'
      setTimeout(() => { thinkOpen.value = false }, 2200)
    },
    fail() {
      clearInterval(timer)
      thinkDone.value = true
      thinkTitle.value = '思考中断'
    }
  }
}

/* ---- 分析 ---- */
async function run() {
  if (running.value || !canAnalyze.value) return
  if (!hasKey.value) { openPanel(); return }

  running.value = true
  err.value = ''
  report.value = ''
  chat.value = []
  const think = startThinking()

  try {
    const res = await fetch(`/api/v1/ai/analyze/${store.currentTaskId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true })
    })
    if (!res.ok || !res.body) {
      let m = 'HTTP ' + res.status
      try { const j = await res.json(); if (j.error) m = j.error } catch { /* 非 JSON 响应 */ }
      throw new Error(m)
    }

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = '', acc = '', first = true

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
          report.value = j.text || acc
        } else if (ev === 'error') {
          throw new Error(j.error || '分析失败')
        }
      }
    }
    if (!report.value.trim()) report.value = '模型没有返回内容'
    think.finish()
  } catch (e) {
    err.value = e.message
    think.fail()
  } finally {
    running.value = false
  }
}

/* ---- 追问 ---- */
async function send() {
  const q = question.value.trim()
  if (!q || chatBusy.value || !store.currentTaskId) return
  question.value = ''
  chat.value.push({ role: 'user', content: q })
  const history = chat.value.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
  const slot = { role: 'assistant', content: '', streaming: true }
  chat.value.push(slot)
  chatBusy.value = true
  await nextTick()
  scrollChat()

  try {
    const res = await fetch(`/api/v1/ai/chat/${store.currentTaskId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history })
    })
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)

    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = '', acc = ''
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
          slot.content = j.text || acc
        } else if (ev === 'error') {
          throw new Error(j.error || '对话失败')
        }
      }
    }
    if (!slot.content.trim()) slot.content = '（无返回内容）'
  } catch (e) {
    slot.content = '对话失败：' + e.message
  } finally {
    slot.streaming = false
    chatBusy.value = false
    scrollChat()
  }
}

function scrollChat() {
  nextTick(() => {
    const el = chatBox.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function copyAll() {
  navigator.clipboard?.writeText(report.value)
}

watch(() => store.currentTaskId, loadCfg, { immediate: true })
</script>

<template>
  <div class="ai-sec">
    <!-- 头部 -->
    <div class="as-head">
      <span class="sec-num">{{ num }}</span>
      <div class="as-logo">
        <img src="/brand/deepseek.svg" alt="" />
      </div>
      <div class="as-title-wrap">
        <div class="as-title">AI 智能分析</div>
        <div class="as-sub">
          DeepSeek 结合本次分析结果给出故障判断
          <template v-if="model"> · <span class="mono">{{ model }}</span></template>
        </div>
      </div>
      <span class="spacer"></span>
      <span v-if="report" class="badge ds">已生成</span>
      <span v-else-if="running" class="badge warning">分析中</span>
      <button v-if="report" class="btn xs ghost" @click="copyAll">复制全文</button>
      <button class="btn xs ghost" @click="openPanel()">设置</button>
    </div>

    <div class="as-body">
      <!-- 未配 Key -->
      <div v-if="!hasKey" class="as-empty">
        <div class="ae-icon">
          <img src="/brand/deepseek.svg" alt="" />
        </div>
        <div class="ae-title">需要配置 DeepSeek API Key</div>
        <div class="ae-desc">
          配置后即可让 AI 结合本次抓包结果，定位故障卡点并给出排查建议
        </div>
        <button class="btn ds" @click="openPanel()">
          <img src="/brand/deepseek-white.svg" alt="" class="ico" />
          配置 API Key
        </button>
      </div>

      <!-- 未分析 -->
      <template v-else-if="!report && !running">
        <div class="as-facts">
          <div v-for="f in facts" :key="f.k" class="af">
            <i>{{ f.k }}</i>
            <b :class="f.cls">{{ f.v }}</b>
          </div>
        </div>
        <div class="as-cta">
          <button class="think-btn" @click="run">
            <img src="/brand/deepseek-white.svg" alt="" class="tb-ico" />
            深度思考
          </button>
          <div class="cta-hint">
            AI 将读取上述 {{ facts[0].v }} 条报文的分析结果，梳理信令与媒体的关联
          </div>
        </div>
      </template>

      <!-- 分析中 / 已出结果 -->
      <template v-else>
        <!-- 思考过程 -->
        <div v-if="steps.length" class="think" :class="{ done: thinkDone }">
          <div class="th-head" @click="thinkOpen = !thinkOpen">
            <img src="/brand/deepseek.svg" alt="" class="whale" />
            <span class="th-title">{{ thinkTitle }}</span>
            <span v-if="!thinkDone" class="th-dots"><i></i><i></i><i></i></span>
            <span class="spacer"></span>
            <span class="th-time mono">{{ elapsed }}s</span>
            <span class="th-arrow" :class="{ open: thinkOpen }">›</span>
          </div>
          <div v-show="thinkOpen" class="th-steps">
            <div v-for="(s, i) in steps" :key="i" class="tstep" :class="s.state">
              <span class="sdot"></span>
              <span class="stxt">{{ s.text }}</span>
              <span class="stime mono">{{ s.time }}</span>
            </div>
          </div>
        </div>

        <!-- 结论卡 -->
        <div v-if="conclusion" class="conclusion">
          <div class="cc-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 16v-4M12 8h.01"/>
            </svg>
            AI 结论
          </div>
          <div class="cc-body" v-html="renderMd(conclusion)"></div>
        </div>

        <!-- 关键发现 -->
        <div v-if="findings.length" class="findings">
          <div class="fd-label">关键发现</div>
          <div class="fd-list">
            <div v-for="(f, i) in findings" :key="i" class="fd">
              <span class="fd-num">{{ i + 1 }}</span>
              <div class="fd-body">
                <b v-if="f.title">{{ f.title }}</b>
                <span>{{ f.desc }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 全文折叠 -->
        <details class="full-report">
          <summary>查看完整报告（{{ report.length }} 字）</summary>
          <div class="fr-body" v-html="renderMd(report)"></div>
        </details>

        <div v-if="err" class="err-box mt-14">{{ err }}</div>

        <!-- 追问 -->
        <div v-if="report" class="ask">
          <div class="ask-log" ref="chatBox">
            <div v-for="(m, i) in chat" :key="i" class="am" :class="m.role">
              <div class="am-av" :class="m.role">
                <img v-if="m.role === 'assistant'" src="/brand/deepseek.svg" alt="" />
                <span v-else>我</span>
              </div>
              <div class="am-bub" :class="{ streaming: m.streaming }">
                <div v-if="m.role === 'assistant'" v-html="renderMd(m.content)"></div>
                <div v-else>{{ m.content }}</div>
              </div>
            </div>
          </div>
          <div class="ask-in">
            <input v-model="question" class="inp" style="flex:1"
                   placeholder="继续追问，例如：这个 SSRC 要去哪里改？"
                   @keyup.enter="send" />
            <button class="btn ds" :disabled="chatBusy || !question.trim()"
                    @click="send">
              发送
            </button>
            <button class="btn" :disabled="running" @click="run">重新分析</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.ai-sec {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  overflow: hidden;
  position: relative;
}
/* 双品牌渐变顶边 */
.ai-sec::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 2.5px;
  background: linear-gradient(90deg, var(--ds), var(--ds-lt) 40%,
              var(--brand) 75%, var(--brand-lt));
}

/* 头部 */
.as-head {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px;
  background: linear-gradient(180deg,
    color-mix(in srgb, var(--ds) 6%, transparent), transparent);
  border-bottom: 1px solid var(--line);
}
.sec-num {
  width: 26px; height: 26px; flex: none;
  border-radius: 8px;
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
  color: var(--ds-lt);
  font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-mono);
}
.as-logo {
  width: 34px; height: 34px; flex: none;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--ds-soft), var(--brand-soft));
  border: 1px solid var(--ds-line);
  display: flex; align-items: center; justify-content: center;
}
.as-logo img { width: 18px; height: auto; }
.as-title-wrap { line-height: 1.3; }
.as-title {
  font-size: 15px; font-weight: 680;
  letter-spacing: -.2px;
}
.as-sub {
  font-size: 11.5px; color: var(--text-3);
  display: flex; align-items: center; gap: 5px;
}
.spacer { flex: 1; }

.as-body { padding: 20px; }

/* 空状态 */
.as-empty {
  text-align: center;
  padding: 32px 24px;
}
.ae-icon {
  width: 48px; height: 48px; margin: 0 auto 14px;
  border-radius: 13px;
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
  display: flex; align-items: center; justify-content: center;
}
.ae-icon img { width: 24px; height: auto; }
.ae-title { font-size: 14px; font-weight: 600; margin-bottom: 7px; }
.ae-desc {
  font-size: 12px; color: var(--text-3);
  line-height: 1.75; margin-bottom: 18px;
  max-width: 420px; margin-left: auto; margin-right: auto;
}

/* 事实 */
.as-facts {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  margin-bottom: 18px;
}
.af {
  background: var(--surface-2);
  padding: 12px 8px;
  text-align: center;
}
.af i {
  display: block; font-size: 10px;
  color: var(--text-4); font-style: normal;
  margin-bottom: 4px;
}
.af b {
  font-size: 17px; font-weight: 680;
  color: var(--text); font-variant-numeric: tabular-nums;
}
.af b.ok { color: var(--ok); }
.af b.warning { color: var(--warning); }
.af b.critical { color: var(--critical); }

.as-cta { text-align: center; padding: 6px 0 4px; }
.think-btn {
  display: inline-flex; align-items: center; gap: 9px;
  height: 44px; padding: 0 28px;
  border-radius: var(--radius);
  border: none;
  background: linear-gradient(135deg, var(--ds), var(--ds-dk) 50%, var(--brand));
  color: #fff;
  font-family: inherit;
  font-size: 14px; font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(77, 107, 254, .3);
  transition: all var(--dur) var(--ease);
}
.think-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 28px rgba(77, 107, 254, .42);
  filter: brightness(1.08);
}
.tb-ico { height: 15px; width: auto; }
.cta-hint {
  font-size: 11.5px; color: var(--text-4);
  margin-top: 12px;
}

/* 思考 */
.think {
  background: linear-gradient(180deg, var(--ds-soft), transparent);
  border: 1px solid var(--ds-line);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 18px;
}
.th-head {
  display: flex; align-items: center; gap: 9px;
  padding: 12px 15px; cursor: pointer;
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
.th-title { font-size: 12.5px; font-weight: 600; color: var(--ds-lt); }
.th-dots { display: inline-flex; gap: 3px; }
.th-dots i {
  width: 3.5px; height: 3.5px; border-radius: 50%;
  background: var(--ds-lt);
  animation: dotPulse 1.3s ease-in-out infinite;
}
.th-dots i:nth-child(2) { animation-delay: .17s }
.th-dots i:nth-child(3) { animation-delay: .34s }
@keyframes dotPulse {
  0%, 60%, 100% { opacity: .28 }
  30% { opacity: 1 }
}
.th-time { font-size: 10px; color: var(--text-4); }
.th-arrow {
  color: var(--text-4); font-size: 15px;
  transition: transform var(--dur) var(--ease);
}
.th-arrow.open { transform: rotate(90deg); }

.th-steps { padding: 0 15px 13px; }
.tstep {
  display: flex; align-items: center; gap: 10px;
  padding: 5px 0; font-size: 12px; color: var(--text-4);
  transition: color var(--dur) var(--ease);
}
.sdot {
  width: 12px; height: 12px; border-radius: 50%;
  border: 1.5px solid var(--line-strong);
  flex: none; position: relative;
}
.tstep.active { color: var(--text-2); }
.tstep.active .sdot {
  border-color: var(--ds);
  animation: ringPulse 1.2s ease infinite;
}
@keyframes ringPulse {
  0% { box-shadow: 0 0 0 0 rgba(77,107,254,.5) }
  70% { box-shadow: 0 0 0 6px rgba(77,107,254,0) }
  100% { box-shadow: 0 0 0 0 rgba(77,107,254,0) }
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

/* 结论卡 */
.conclusion {
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--brand-line);
  background: linear-gradient(135deg, var(--brand-soft), transparent 60%);
  margin-bottom: 16px;
}
.cc-label {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 16px;
  background: var(--brand-soft);
  border-bottom: 1px solid var(--brand-line);
  font-size: 12px; font-weight: 650;
  color: var(--brand-lt);
}
.cc-label svg { width: 14px; height: 14px; }
.cc-body {
  padding: 14px 16px;
  font-size: 13px; line-height: 1.82;
  color: var(--text);
}
.cc-body :deep(p) { margin: 6px 0; }
.cc-body :deep(strong) { color: var(--brand-lt); }
.cc-body :deep(code) {
  background: var(--surface-3);
  padding: 1.5px 6px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 11.5px;
  color: #e2c08d;
}

/* 关键发现 */
.findings { margin-bottom: 16px; }
.fd-label {
  font-size: 11px; color: var(--text-4);
  letter-spacing: .4px; margin-bottom: 9px;
  text-transform: uppercase;
}
.fd-list { display: flex; flex-direction: column; gap: 8px; }
.fd {
  display: flex; gap: 11px;
  padding: 11px 14px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  transition: border-color var(--dur) var(--ease);
}
.fd:hover { border-color: var(--line-strong); }
.fd-num {
  width: 19px; height: 19px; flex: none;
  border-radius: 50%;
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
  color: var(--ds-lt);
  font-size: 10.5px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  margin-top: 1px;
}
.fd-body { font-size: 12.5px; line-height: 1.7; color: var(--text-2); }
.fd-body b {
  color: var(--text); font-weight: 600;
  margin-right: 6px;
}

/* 完整报告 */
.full-report {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  margin-bottom: 16px;
}
.full-report summary {
  padding: 11px 15px;
  background: var(--surface-2);
  font-size: 12px; color: var(--text-2);
  cursor: pointer;
  user-select: none;
  transition: background var(--dur) var(--ease);
}
.full-report summary:hover { background: var(--surface-3); }
.fr-body {
  padding: 16px;
  font-size: 12.5px; line-height: 1.82;
  color: var(--text-2);
  border-top: 1px solid var(--line);
}
.fr-body :deep(h2) {
  font-size: 13.5px; color: var(--text); font-weight: 650;
  margin: 16px 0 8px; padding-left: 9px;
  border-left: 2.5px solid var(--ds);
}
.fr-body :deep(h3) {
  font-size: 12.5px; color: var(--text);
  font-weight: 620; margin: 12px 0 6px;
}
.fr-body :deep(p) { margin: 7px 0; }
.fr-body :deep(ul), .fr-body :deep(ol) { margin: 7px 0 7px 18px; }
.fr-body :deep(li) { margin: 3px 0; }
.fr-body :deep(strong) { color: var(--text); }
.fr-body :deep(code) {
  background: var(--surface-3);
  padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 11px;
  color: #e2c08d;
}

/* 追问 */
.ask {
  border-top: 1px solid var(--line);
  padding-top: 14px;
}
.ask-log {
  max-height: 280px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 11px;
  margin-bottom: 12px;
}
.ask-log:empty { display: none; }
.am { display: flex; gap: 9px; }
.am.user { flex-direction: row-reverse; }
.am-av {
  width: 24px; height: 24px; border-radius: 6px;
  flex: none; display: flex; align-items: center; justify-content: center;
  font-size: 10.5px; font-weight: 600;
}
.am-av.assistant {
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
}
.am-av.assistant img { width: 14px; height: auto; }
.am-av.user {
  background: var(--surface-3);
  border: 1px solid var(--line-2);
  color: var(--text-3);
}
.am-bub {
  max-width: calc(100% - 38px);
  padding: 9px 13px; border-radius: 10px;
  font-size: 12px; line-height: 1.75;
}
.am.assistant .am-bub {
  background: var(--ds-soft);
  border: 1px solid rgba(77,107,254,.16);
  color: var(--text-2);
}
.am.user .am-bub {
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  color: var(--text-2);
}
.am-bub.streaming::after {
  content: '▊'; color: var(--ds-lt);
  animation: blink 1s step-end infinite;
  margin-left: 2px;
}
@keyframes blink { 50% { opacity: 0 } }
.am-bub :deep(p) { margin: 4px 0; }
.am-bub :deep(code) {
  background: var(--surface-3);
  padding: 1px 4px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 10.5px;
  color: #e2c08d;
}
.ask-in { display: flex; gap: 8px; align-items: center; }
</style>
