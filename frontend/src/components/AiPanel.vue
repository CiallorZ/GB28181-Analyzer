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
import { ref, computed, watch, nextTick } from 'vue'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import { renderMd } from '../utils/markdown'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['update:open'])

const store = useTaskStore()

const tab = ref('report')
const report = ref('')
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

const cfg = ref({ has_key: false, key_hint: '', model: '', base_url: '' })
const keyInput = ref('')
const modelInput = ref('')
const baseInput = ref('')
const cfgMsg = ref('')
const cfgBusy = ref(false)
const testing = ref(false)

const PLAN = ['读取分析结果', '梳理信令与媒体关联', '定位故障卡点', '生成排查报告']

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
      setTimeout(() => { thinkOpen.value = false }, 2400)
    },
    fail() {
      clearInterval(timer)
      thinkDone.value = true
      thinkTitle.value = '思考中断'
    }
  }
}

/* ---- 报告 ---- */
async function runAnalyze() {
  if (running.value || !canAnalyze.value) return
  if (!cfg.value.has_key) { tab.value = 'config'; return }

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
      try { const j = await res.json(); if (j.error) m = j.error } catch {}
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
async function sendQuestion() {
  const q = question.value.trim()
  if (!q || chatBusy.value || !store.currentTaskId) return

  question.value = ''
  chat.value.push({ role: 'user', content: q })
  const history = chat.value.slice(0, -1).map(m => ({
    role: m.role, content: m.content
  }))
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
    if (!res.ok || !res.body) {
      let m = 'HTTP ' + res.status
      try { const j = await res.json(); if (j.error) m = j.error } catch {}
      throw new Error(m)
    }

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

function copyReport() {
  navigator.clipboard?.writeText(report.value)
}

watch(() => props.open, async (v) => {
  if (!v) return
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
        <aside class="drawer">
          <!-- 双品牌头部 -->
          <div class="head">
            <div class="head-glow"></div>
            <div class="head-in">
              <div class="logos">
                <img src="/brand/deepseek-white.svg" alt="" class="lg-ds" />
              </div>
              <div class="head-txt">
                <div class="head-name">DeepSeek 智能分析</div>
                <div class="head-sub">
                  <span class="dot-brand"></span>
                  结合本次抓包分析结果
                  <template v-if="cfg.model"> · <span class="mono">{{ cfg.model }}</span></template>
                </div>
              </div>
              <div class="spacer"></div>
              <button class="hbtn" @click="tab = tab === 'config' ? 'report' : 'config'"
                      :title="tab === 'config' ? '返回' : '设置'">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 008.6 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 8.6a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>
                </svg>
              </button>
              <button class="hbtn" @click="close" title="关闭">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
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
                deepseek-flash 默认开启 thinking 模式会返回空内容，
                后端已显式关闭该模式
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
            <div v-if="!canAnalyze" class="empty">
              请先完成一次抓包分析
              <div class="hint">分析完成后才能让 AI 定位故障卡点</div>
            </div>

            <template v-else>
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
                <div class="start-icon">
                  <img src="/brand/deepseek.svg" alt="" />
                </div>
                <div class="start-title">让 DeepSeek 定位故障卡点</div>
                <div class="start-desc">
                  AI 将基于上述事实，分析信令与媒体的关联关系，
                  指出最可能的问题位置并给出可验证的排查步骤
                </div>
                <button class="think-btn" @click="runAnalyze"
                        :disabled="running || !cfg.has_key">
                  <img src="/brand/deepseek-white.svg" alt="" class="btn-ico" />
                  深度思考
                </button>
                <div v-if="!cfg.has_key" class="hint mt-10">需要先配置 API Key</div>
              </div>

              <!-- 思考过程 -->
              <div v-if="steps.length" class="think" :class="{ done: thinkDone }">
                <div class="think-head" @click="thinkOpen = !thinkOpen">
                  <img src="/brand/deepseek.svg" alt="" class="whale" />
                  <span class="t-title">{{ thinkTitle }}</span>
                  <span v-if="!thinkDone" class="t-dots"><i></i><i></i><i></i></span>
                  <span class="spacer"></span>
                  <span class="t-time mono">{{ elapsed }}s</span>
                  <span class="t-arrow" :class="{ open: thinkOpen }">›</span>
                </div>
                <div v-show="thinkOpen" class="t-steps">
                  <div v-for="(s, i) in steps" :key="i" class="tstep" :class="s.state">
                    <span class="sdot"></span>
                    <span class="stxt">{{ s.text }}</span>
                    <span class="stime mono">{{ s.time }}</span>
                  </div>
                </div>
              </div>

              <!-- 报告 -->
              <div v-if="report" class="report">
                <div class="r-tools">
                  <button class="btn-mini" @click="copyReport">复制</button>
                  <button class="btn-mini" @click="runAnalyze" :disabled="running">
                    重新分析
                  </button>
                </div>
                <div class="md" v-html="renderMd(report)"></div>
              </div>

              <div v-if="err" class="err-box" style="margin:12px 14px">{{ err }}</div>

              <!-- 对话 -->
              <div v-if="report" class="chat">
                <div class="chat-log" ref="chatBox">
                  <div v-for="(m, i) in chat" :key="i" class="cmsg" :class="m.role">
                    <div class="cav" :class="m.role">
                      <img v-if="m.role === 'assistant'" src="/brand/deepseek.svg" alt="" />
                      <span v-else>我</span>
                    </div>
                    <div class="cbub" :class="{ streaming: m.streaming }">
                      <div v-if="m.role === 'assistant'" v-html="renderMd(m.content)"></div>
                      <div v-else>{{ m.content }}</div>
                    </div>
                  </div>
                </div>
                <div class="chat-in">
                  <textarea v-model="question" rows="1"
                            placeholder="继续追问，例如：这个 SSRC 要去哪里改？"
                            @keydown.enter.exact.prevent="sendQuestion"></textarea>
                  <button class="send" @click="sendQuestion"
                          :disabled="chatBusy || !question.trim()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                      <line x1="22" y1="2" x2="11" y2="13"/>
                      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                    </svg>
                  </button>
                </div>
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
  background: rgba(0, 0, 0, .58);
  backdrop-filter: blur(3px);
  display: flex; justify-content: flex-end;
}
.drawer {
  width: 600px; max-width: 94vw; height: 100%;
  background: var(--bg-2);
  border-left: 1px solid var(--line-strong);
  display: flex; flex-direction: column;
  box-shadow: -10px 0 50px rgba(0, 0, 0, .5);
}

.slide-enter-active, .slide-leave-active { transition: opacity .2s; }
.slide-enter-active .drawer, .slide-leave-active .drawer {
  transition: transform .28s var(--ease);
}
.slide-enter-from, .slide-leave-to { opacity: 0; }
.slide-enter-from .drawer, .slide-leave-to .drawer {
  transform: translateX(100%);
}

/* ===== 头部：双品牌融合 ===== */
.head {
  position: relative;
  flex: none;
  background: linear-gradient(120deg,
    var(--ds-dk) 0%, var(--ds) 38%, #8B1A2A 72%, var(--brand) 100%);
  overflow: hidden;
}
.head-glow {
  position: absolute; inset: 0;
  background:
    radial-gradient(320px 120px at 18% 0%, rgba(255,255,255,.22), transparent 70%),
    radial-gradient(280px 100px at 88% 100%, rgba(255,255,255,.14), transparent 70%);
}
.head-in {
  position: relative;
  display: flex; align-items: center; gap: 12px;
  padding: 15px 16px;
}
.logos { display: flex; align-items: center; }
.lg-ds { height: 24px; width: auto; filter: drop-shadow(0 2px 6px rgba(0,0,0,.3)); }
.head-txt { line-height: 1.3; }
.head-name {
  font-size: 14.5px; font-weight: 680;
  color: #fff; letter-spacing: -.1px;
}
.head-sub {
  font-size: 10.5px; color: rgba(255,255,255,.78);
  display: flex; align-items: center; gap: 5px;
}
.dot-brand {
  width: 5px; height: 5px; border-radius: 50%;
  background: #fff; opacity: .85;
  box-shadow: 0 0 6px rgba(255,255,255,.8);
}
.hbtn {
  width: 28px; height: 28px;
  border-radius: 7px;
  background: rgba(255,255,255,.14);
  border: 1px solid rgba(255,255,255,.18);
  color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: .15s;
  flex: none;
}
.hbtn:hover { background: rgba(255,255,255,.26); }
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
  font-size: 10.5px; color: var(--text-4);
  letter-spacing: .4px; margin-bottom: 8px;
  text-transform: uppercase;
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
  display: block; font-size: 9.5px;
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
.start-icon {
  width: 56px; height: 56px; margin: 0 auto 16px;
  border-radius: 15px;
  background: linear-gradient(135deg, var(--ds-soft), var(--brand-soft));
  border: 1px solid var(--ds-line);
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
.think-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 11px 26px;
  border-radius: var(--radius);
  background: linear-gradient(135deg, var(--ds), var(--ds-dk) 55%, var(--brand));
  border: none;
  color: #fff; font-size: 13.5px; font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(77, 107, 254, .32);
  transition: all var(--dur) var(--ease);
}
.think-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(77, 107, 254, .42);
  filter: brightness(1.08);
}
.think-btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-ico { height: 14px; width: auto; }

/* 思考 */
.think {
  margin: 14px 16px 0;
  background: linear-gradient(180deg, var(--ds-soft), transparent);
  border: 1px solid var(--ds-line);
  border-radius: var(--radius);
  overflow: hidden;
}
.think-head {
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

/* 报告 */
.report { padding: 14px 16px 8px; }
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
  color: #e2c08d;
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
  max-height: 300px; overflow-y: auto;
  padding: 14px 16px 0;
  display: flex; flex-direction: column; gap: 12px;
}
.chat-log:empty { display: none; }
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
.cbub {
  max-width: calc(100% - 38px);
  padding: 9px 13px; border-radius: 10px;
  font-size: 12px; line-height: 1.75;
}
.cmsg.assistant .cbub {
  background: var(--ds-soft);
  border: 1px solid rgba(77,107,254,.16);
  color: var(--text-2);
}
.cmsg.user .cbub {
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  color: var(--text-2);
}
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
  font-size: 10.5px; color: #e2c08d;
}
.cbub :deep(ul) { margin: 5px 0 5px 16px; }

.chat-in {
  display: flex; gap: 9px; align-items: flex-end;
  padding: 12px 16px 16px;
}
.chat-in textarea {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--line-2);
  border-radius: 10px;
  padding: 9px 12px;
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  resize: none;
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
  background: linear-gradient(135deg, var(--ds), var(--ds-dk));
  border: none; color: #fff;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: .15s;
  box-shadow: 0 2px 10px rgba(77,107,254,.3);
}
.send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(77,107,254,.45);
}
.send:disabled { opacity: .4; cursor: not-allowed; }
.send svg { width: 14px; height: 14px; }
</style>
