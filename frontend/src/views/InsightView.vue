<script setup>
/**
 * 智能洞察：面向单个已完成任务的分析驾驶舱。
 *
 * 与工作台的「瀑布式全量结果」不同，这里只回答三个问题：
 *   结论是什么（verdict hero）→ 各阶段如何得出（结论时间线）→ 下一步做什么（AI 会诊 / 证据页）。
 * 后端 verdict.stages 是新增字段，旧任务可能没有；缺失时由 overview 汇总派生出
 * 只读的「概览数据」阶段，并明确标注其不是规则结论。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import { cachedLoad, cacheKey, taskRevision } from '../utils/taskCache'

const router = useRouter()
const store = useTaskStore()

const task = ref(null)
const overview = ref(null)
const loading = ref(false)
const err = ref('')
const expandedKeys = ref([])
let loadSeq = 0

const taskId = computed(() => store.currentTaskId)
const summary = computed(() => overview.value?.summary || store.task?.summary || {})
const stale = (seq, tid) => seq !== loadSeq || tid !== store.currentTaskId

async function loadAll() {
  const tid = store.currentTaskId
  if (!tid) {
    task.value = null
    overview.value = null
    return
  }
  const seq = ++loadSeq
  loading.value = true
  err.value = ''
  try {
    const current = await store.loadTask(tid)
    if (stale(seq, tid)) return
    task.value = current
    if (current.status !== 'completed') return
    // 与工作台共用「任务 ID + 完成时间」版本缓存，切换页面不重复取 overview。
    const rev = taskRevision(current)
    const ov = await cachedLoad(cacheKey(tid, rev, 'overview'), () => api.overview(tid))
    if (stale(seq, tid)) return
    overview.value = ov
  } catch (error) {
    if (!stale(seq, tid)) err.value = error.message || '读取分析结果失败'
  } finally {
    if (!stale(seq, tid)) loading.value = false
  }
}

watch(taskId, () => {
  task.value = null
  overview.value = null
  expandedKeys.value = []
  err.value = ''
  loadAll()
}, { immediate: true })

/* ---------------- 结论 ---------------- */
const VD_STATUS = {
  blocked: { label: '存在阻断问题', icon: 'warning' },
  attention: { label: '需关注', icon: 'warning' },
  observation: { label: '待观察', icon: 'info' },
  healthy: { label: '已确认正常', icon: 'check' }
}
const CONFIDENCE = { confirmed: '已确认', suspected: '疑似', insufficient: '证据不足' }
const verdict = computed(() => {
  const v = summary.value.verdict
  return v && typeof v === 'object' && v.status && v.headline ? v : null
})
// 未知状态一律按「待观察」呈现，避免把没见过的状态染成正常绿。
const verdictStatusKey = computed(() => verdict.value && VD_STATUS[verdict.value.status]
  ? verdict.value.status : 'observation')
const verdictStatus = computed(() => VD_STATUS[verdictStatusKey.value])
const confidenceLabel = computed(() => CONFIDENCE[verdict.value?.confidence] || '')
const confidenceTone = computed(() => ({
  confirmed: 'ok', suspected: 'warning', insufficient: 'info'
}[verdict.value?.confidence] || 'info'))
const actions = computed(() => Array.isArray(verdict.value?.actions)
  ? verdict.value.actions.filter(a => typeof a === 'string' && a.trim()).slice(0, 4)
  : [])
const leadRules = computed(() => Array.isArray(verdict.value?.lead_rule_ids)
  ? verdict.value.lead_rule_ids.filter(v => v != null).map(String).slice(0, 5)
  : [])

/* ---------------- 根因链 ---------------- */
// 后端新增的 summary.root_cause 是附加字段；缺失时整块不显示，不影响其他结论。
const rootCause = computed(() => {
  const r = summary.value.root_cause
  return r && typeof r === 'object' && r.failure_stage && r.label ? r : null
})
const rootCauseTone = computed(() => ({
  confirmed: 'critical', suspected: 'warning', insufficient: 'info'
}[rootCause.value?.confidence] || 'info'))

/* ---------------- 阶段时间线 ---------------- */
const STAGE_LABEL = {
  signal: '信令会话', negotiation: '媒体协商', media: '媒体传输',
  codec: '编码解析', capture: '抓包覆盖'
}
const STAGE_ICON = {
  signal: 'signal', negotiation: 'wave', media: 'wave',
  codec: 'codec', capture: 'file'
}
const STAGE_ROUTE = {
  signal: 'sip', negotiation: 'sip', media: 'media',
  codec: 'media', capture: 'packets'
}
const STAGE_STATUS = {
  ok: { tone: 'ok', label: '正常' }, healthy: { tone: 'ok', label: '正常' },
  pass: { tone: 'ok', label: '正常' }, success: { tone: 'ok', label: '正常' },
  warning: { tone: 'warning', label: '需关注' }, attention: { tone: 'warning', label: '需关注' },
  suspected: { tone: 'warning', label: '疑似' },
  observation: { tone: 'info', label: '待观察' }, info: { tone: 'info', label: '信息' },
  insufficient: { tone: 'info', label: '证据不足' },
  critical: { tone: 'critical', label: '阻断' }, blocked: { tone: 'critical', label: '阻断' },
  fail: { tone: 'critical', label: '异常' }, failed: { tone: 'critical', label: '异常' },
  error: { tone: 'critical', label: '异常' }
}

function normalizeStage(raw, index) {
  if (!raw || typeof raw !== 'object') return null
  const key = typeof raw.key === 'string' && raw.key ? raw.key : `stage-${index + 1}`
  const status = String(raw.status || '').toLowerCase()
  const mapped = STAGE_STATUS[status]
  return {
    key,
    label: typeof raw.label === 'string' && raw.label ? raw.label : (STAGE_LABEL[key] || `阶段 ${index + 1}`),
    summary: typeof raw.summary === 'string' ? raw.summary : '',
    hint: typeof raw.evidence_hint === 'string' ? raw.evidence_hint : '',
    rules: Array.isArray(raw.rule_ids)
      ? raw.rule_ids.filter(v => v != null).map(String).slice(0, 6) : [],
    tone: mapped?.tone || 'info',
    statusLabel: mapped?.label || (status ? String(raw.status) : '已记录'),
    icon: STAGE_ICON[key] || 'info',
    derived: false
  }
}

// 旧任务没有 verdict.stages：用真实汇总数字派生各阶段概览，不编造规则结论。
function deriveStages(s) {
  const d = s.diagnostics || {}
  const num = v => Number(v) || 0
  const hasSignal = s.session_count != null
  const rows = [
    {
      key: 'signal',
      summary: hasSignal
        ? `识别 ${num(s.session_count)} 个 SIP 会话，信令成功 ${num(s.signal_success)} 个` +
          (s.signal_success_rate != null ? `（成功率 ${num(s.signal_success_rate).toFixed(1)}%）` : '')
        : '任务汇总未提供信令统计'
    },
    {
      key: 'negotiation',
      summary: hasSignal
        ? `基于 ${num(s.session_count)} 个会话的 SDP 协商记录，详细过程请查看 SIP 证据页`
        : '未捕获 SIP 协商过程，请查看 SIP 证据页'
    },
    {
      key: 'media',
      summary: `发现 ${num(s.total_streams)} 条 RTP 流，${num(s.sessions_with_media)} 个会话收到媒体`
    },
    {
      key: 'codec',
      summary: num(s.total_streams)
        ? `已解析 ${num(s.total_streams)} 条流的编码信息，格式与分辨率请查看媒体分析`
        : '本任务未捕获可解析的媒体编码'
    },
    {
      key: 'capture',
      summary: `共 ${num(s.packet_count).toLocaleString()} 个报文，${num(s.capture_warnings)} 项抓包提示；` +
        `${num(d.critical)} 严重 · ${num(d.warning)} 警告`
    }
  ]
  return rows.map(row => ({
    ...row,
    label: STAGE_LABEL[row.key],
    icon: STAGE_ICON[row.key],
    tone: 'info',
    statusLabel: '概览数据',
    rules: [],
    hint: '该阶段信息由任务汇总推导，不是规则引擎结论。打开「查看证据」可核对原始分析结果。',
    derived: true
  }))
}

const stages = computed(() => {
  const raw = verdict.value?.stages
  if (Array.isArray(raw) && raw.length) {
    const normalized = raw.slice(0, 5).map(normalizeStage).filter(Boolean)
    if (normalized.length) return normalized
  }
  return deriveStages(summary.value)
})
const stagesFromVerdict = computed(() => stages.value.some(s => !s.derived))

function isOpen(key) { return expandedKeys.value.includes(key) }
function toggleStage(key) {
  expandedKeys.value = isOpen(key)
    ? expandedKeys.value.filter(k => k !== key)
    : [...expandedKeys.value, key]
}
function evidenceTarget(stage) {
  return { name: STAGE_ROUTE[stage.key] || 'diagnostics', query: { task: store.currentTaskId } }
}

/* ---------------- 证据入口 ---------------- */
const diags = computed(() => summary.value.diagnostics || {})
const diagTotal = computed(() => ['critical', 'warning', 'info', 'unknown']
  .reduce((n, k) => n + (Number(diags.value[k]) || 0), 0))
const diagTone = computed(() => num(diags.value.critical) ? 'critical'
  : num(diags.value.warning) ? 'warning' : 'ok')

function num(v) { return Number(v) || 0 }
function count(v) { return num(v).toLocaleString() }

const shortcuts = computed(() => [
  {
    key: 'diagnostics', name: 'diagnostics', icon: 'warning', label: '诊断结论',
    value: count(diagTotal.value),
    sub: `${num(diags.value.critical)} 严重 · ${num(diags.value.warning)} 警告`,
    tone: diagTone.value
  },
  {
    key: 'sip', name: 'sip', icon: 'signal', label: 'SIP 信令',
    value: count(summary.value.session_count), sub: '点播会话', tone: ''
  },
  {
    key: 'media', name: 'media', icon: 'wave', label: '媒体分析',
    value: count(summary.value.total_streams), sub: 'RTP 流', tone: ''
  },
  {
    key: 'packets', name: 'packets', icon: 'file', label: '原始报文',
    value: count(summary.value.packet_count), sub: '抓包报文', tone: ''
  }
])

const TASK_STATUS = {
  pending: ['待分析', 'unknown'], analyzing: ['分析中', 'brand'],
  completed: ['已完成', 'ok'], failed: ['失败', 'critical'],
  cancelled: ['已取消', 'unknown']
}
const taskStatus = computed(() => TASK_STATUS[task.value?.status] || ['状态未知', 'unknown'])

function goWorkbench() { router.push({ name: 'task', params: { id: store.currentTaskId } }) }
function goTasks() { router.push({ name: 'tasks' }) }
function goHome() { router.push({ name: 'workbench' }) }
function goDiagnostics() {
  router.push({ name: 'diagnostics', query: { task: store.currentTaskId } })
}
function consult() { store.openAiPanel('general') }
</script>

<template>
  <div class="page insight-page">
    <!-- 未选择任务 -->
    <section v-if="!taskId" class="ins-placeholder" aria-labelledby="ins-no-task-title">
      <span class="ins-placeholder-icon"><AppIcon name="file" /></span>
      <h1 id="ins-no-task-title">尚未选择分析任务</h1>
      <p>智能洞察基于已完成任务的结构化结论生成。请先上传抓包文件，或从历史任务中选择一个任务。</p>
      <div class="ins-placeholder-actions">
        <button class="btn" @click="goHome">返回工作台</button>
        <button class="btn ghost" @click="goTasks">历史任务</button>
      </div>
    </section>

    <template v-else>
      <!-- 首次加载骨架 -->
      <div v-if="loading && !task" class="ins-skeleton" role="status" aria-label="正在加载智能洞察">
        <div class="ins-sk-head">
          <div class="ins-sk-block ins-sk-line lg"></div>
          <div class="ins-sk-block ins-sk-line sm"></div>
        </div>
        <div class="ins-sk-block ins-sk-hero"></div>
        <div class="ins-sk-block ins-sk-line md"></div>
        <div class="ins-sk-stages">
          <div v-for="n in 4" :key="n" class="ins-sk-block ins-sk-stage"></div>
        </div>
        <p class="ins-skeleton-note">正在读取任务结论…</p>
      </div>

      <!-- 读取失败 -->
      <section v-else-if="err && !task" class="ins-placeholder" role="alert">
        <span class="ins-placeholder-icon"><AppIcon name="warning" /></span>
        <h1>无法读取智能洞察</h1>
        <p>{{ err }}</p>
        <div class="ins-placeholder-actions">
          <button class="btn" @click="loadAll">重试</button>
          <button class="btn ghost" @click="goTasks">历史任务</button>
        </div>
      </section>

      <template v-else-if="task">
        <!-- 任务上下文 -->
        <header class="ins-header">
          <div class="ins-header-main">
            <div class="ins-eyebrow"><AppIcon name="codec" /> 智能洞察 · 任务结论</div>
            <h1 class="ins-title truncate" :title="task.file?.filename || task.name">
              {{ task.file?.filename || task.name || `任务 #${taskId}` }}
            </h1>
            <div class="ins-meta">
              <span class="mono-sm">任务 #{{ taskId }}</span>
              <span class="badge" :class="taskStatus[1]">{{ taskStatus[0] }}</span>
              <span v-if="task.file?.duration != null" class="mono-sm ins-duration">
                {{ num(task.file.duration).toFixed(1) }}s 抓包
              </span>
            </div>
          </div>
          <button class="btn ins-back" @click="goWorkbench"><AppIcon name="back" /> 返回工作台</button>
        </header>

        <!-- 未完成任务 -->
        <section v-if="task.status !== 'completed'" class="ins-placeholder">
          <span class="ins-placeholder-icon"><AppIcon name="info" /></span>
          <h1>分析尚未完成</h1>
          <p>任务当前处于「{{ taskStatus[0] }}」状态。结构化结论在分析完成后生成，请稍后返回。</p>
          <div class="ins-placeholder-actions">
            <button class="btn" @click="goWorkbench">返回工作台</button>
            <button class="btn ghost" @click="loadAll">重新读取</button>
          </div>
        </section>

        <template v-else>
          <div v-if="err" class="err-box flat" role="alert">
            {{ err }} <button class="btn sm" @click="loadAll">重试</button>
          </div>

          <!-- 主结论 -->
          <section v-if="verdict" class="vd-card ins-hero" :class="'vd-' + verdictStatusKey"
                   aria-labelledby="ins-verdict-title">
            <div class="vd-card-main">
              <span class="vd-status" :class="'vd-' + verdictStatusKey" role="status"
                    :aria-label="`结论状态：${verdictStatus.label}`">
                <AppIcon :name="verdictStatus.icon" />{{ verdictStatus.label }}
              </span>
              <h2 id="ins-verdict-title" class="vd-headline">{{ verdict.headline }}</h2>
              <p class="vd-meta">
                结论置信度 · {{ confidenceLabel || '未标注' }}
                <template v-if="leadRules.length"> · 主导规则 {{ leadRules.join(' / ') }}</template>
              </p>
              <ol v-if="actions.length" class="vd-actions">
                <li v-for="(action, i) in actions" :key="i" :data-n="i + 1">{{ action }}</li>
              </ol>
            </div>
            <div class="vd-card-side">
              <span class="ins-confidence-label">结论置信度</span>
              <span class="ins-confidence" :class="confidenceTone">{{ confidenceLabel || '未标注' }}</span>
              <button class="btn sm" @click="goDiagnostics">
                查看诊断 <AppIcon name="forward" />
              </button>
            </div>
          </section>

          <!-- 老任务：无结构化结论时的空状态 -->
          <section v-else class="vd-card ins-hero vd-observation ins-verdict-empty"
                   aria-labelledby="ins-verdict-empty-title">
            <div class="vd-card-main">
              <span class="vd-status vd-observation"><AppIcon name="info" />结论未生成</span>
              <h2 id="ins-verdict-empty-title" class="vd-headline">该任务暂无结构化结论</h2>
              <p class="vd-meta">
                旧版本任务可能没有可供会诊引用的结论数据。分阶段概览与证据页仍可正常使用。
              </p>
              <div class="ins-empty-actions">
                <button class="btn" @click="goWorkbench">返回工作台</button>
                <button class="btn ghost" @click="goTasks">历史任务</button>
              </div>
            </div>
          </section>

          <!-- 根因链：最可能的失败环节，来自本地规则推理 -->
          <section v-if="rootCause" class="ins-section ins-root-cause"
                   :class="'ins-rc-' + rootCauseTone" aria-labelledby="ins-rc-title">
            <div class="ins-section-head">
              <div class="ins-section-heading">
                <h2 id="ins-rc-title" class="ins-section-title">根因链</h2>
                <p class="ins-section-sub">按抓包范围 → 信令 → 协商 → 媒体 → 编码逐层定位 · 本地规则推导</p>
              </div>
              <span class="ins-rc-stage">{{ rootCause.label }}</span>
            </div>
            <ol class="ins-rc-chain">
              <li v-for="(step, i) in rootCause.chain" :key="i">{{ step }}</li>
            </ol>
            <p v-if="rootCause.next_check" class="ins-rc-next">
              <AppIcon name="forward" /> 下一步：{{ rootCause.next_check }}
            </p>
          </section>

          <!-- 分阶段结论 -->
          <section class="ins-section" aria-labelledby="ins-timeline-title">
            <div class="ins-section-head">
              <div class="ins-section-heading">
                <h2 id="ins-timeline-title" class="ins-section-title">分阶段结论</h2>
                <p class="ins-section-sub">
                  {{ stagesFromVerdict ? '来自任务结论' : '由任务汇总推导 · 非规则结论' }} ·
                  点击任一步骤查看依据
                </p>
              </div>
              <span class="ins-section-count">{{ stages.length }} / 5</span>
            </div>

            <div class="ins-stages">
              <article v-for="(stage, i) in stages" :key="stage.key"
                       class="ins-stage" :class="[`tone-${stage.tone}`, { open: isOpen(stage.key) }]"
                       :style="{ animationDelay: `${i * 40}ms` }">
                <div class="ins-stage-row">
                  <button type="button" class="ins-stage-toggle" :aria-expanded="isOpen(stage.key)"
                          @click="toggleStage(stage.key)">
                    <span class="ins-stage-rail">
                      <span class="ins-stage-dot"><AppIcon :name="stage.icon" /></span>
                    </span>
                    <span class="ins-stage-main">
                      <span class="ins-stage-titleline">
                        <strong class="ins-stage-label">{{ stage.label }}</strong>
                        <span class="ins-stage-status">{{ stage.statusLabel }}</span>
                        <span v-if="stage.derived" class="ins-derived">推导</span>
                      </span>
                      <span class="ins-stage-summary">{{ stage.summary || '暂无阶段摘要' }}</span>
                      <span v-if="stage.rules.length" class="ins-rules">
                        <span v-for="rule in stage.rules" :key="rule" class="ins-rule mono">{{ rule }}</span>
                      </span>
                    </span>
                    <AppIcon name="down" class="ins-stage-chev" />
                  </button>
                  <router-link class="ins-evidence-link" :to="evidenceTarget(stage)"
                               :aria-label="`查看${stage.label}的证据`">
                    查看证据 <AppIcon name="forward" />
                  </router-link>
                </div>
                <div class="ins-stage-expand" :aria-hidden="!isOpen(stage.key)">
                  <div class="ins-stage-expand-inner">
                    <p class="ins-hint-body">
                      <span class="ins-hint-label">依据提示</span>
                      {{ stage.hint || '该阶段未提供额外依据说明，请打开证据页查看原始分析结果。' }}
                    </p>
                  </div>
                </div>
              </article>
            </div>
          </section>

          <!-- AI 会诊 -->
          <section class="ins-ai" aria-labelledby="ins-ai-title">
            <span class="ins-ai-icon"><img src="/brand/deepseek.svg" alt="" width="22" height="22" /></span>
            <div class="ins-ai-copy">
              <h2 id="ins-ai-title">让 AI 基于以上结论做二次研判</h2>
              <p>将结论、分阶段依据与关键规则交给 DeepSeek 交叉验证，生成可执行的排障建议。</p>
            </div>
            <button class="btn ds" @click="consult">
              <img src="/brand/deepseek.svg" alt="" width="16" height="16" /> 发起 AI 会诊
              <AppIcon name="forward" />
            </button>
          </section>

          <!-- 证据快捷入口 -->
          <section class="ins-section" aria-labelledby="ins-shortcuts-title">
            <div class="ins-section-head">
              <div class="ins-section-heading">
                <h2 id="ins-shortcuts-title" class="ins-section-title">证据入口</h2>
                <p class="ins-section-sub">按分析层级快速定位原始数据</p>
              </div>
            </div>
            <div class="ins-shortcuts">
              <router-link v-for="item in shortcuts" :key="item.key" class="ins-shortcut"
                           :class="item.tone ? `tone-${item.tone}` : ''"
                           :to="{ name: item.name, query: { task: taskId } }">
                <span class="ins-shortcut-top">
                  <span class="ins-shortcut-icon"><AppIcon :name="item.icon" /></span>
                  <AppIcon name="forward" class="ins-shortcut-arrow" />
                </span>
                <span class="ins-shortcut-label">{{ item.label }}</span>
                <span class="ins-shortcut-value">{{ item.value }}</span>
                <span class="ins-shortcut-sub">{{ item.sub }}</span>
              </router-link>
            </div>
          </section>
        </template>
      </template>
    </template>
  </div>
</template>

<style src="../styles/verdict.css"></style>
<style src="../styles/insight.css"></style>
