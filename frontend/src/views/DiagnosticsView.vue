<script setup>
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import AiFocusButton from '../components/AiFocusButton.vue'
import MetricCard from '../components/MetricCard.vue'
import PageNav from '../components/PageNav.vue'
import { useTaskStore } from '../stores/task'

const router = useRouter()
const store = useTaskStore()
const items = ref([])
const ruleStats = ref(null)
const rules = ref([])
const sevFilter = ref('')
const ruleFilter = ref('')
const err = ref('')
const expanded = ref({})
const selectedId = ref(null)

const total = ref(0)
const page = ref(0)
const loading = ref(false)
let request = 0

async function load(append = false) {
  const id = ++request
  const task = store.currentTaskId
  const next = append ? page.value + 1 : 1
  err.value = ''
  if (!append) {
    items.value = []
    expanded.value = {}
    selectedId.value = null
    total.value = 0
    page.value = 0
    ruleStats.value = null
  }
  loading.value = Boolean(task)
  if (!task) return
  try {
    const [d, rs, rl] = await Promise.all([
      api.diagnostics(task, {
        page: next, page_size: 200,
        severity: sevFilter.value || undefined,
        rule_id: ruleFilter.value || undefined
      }),
      append ? ruleStats.value : api.ruleStats(task),
      rules.value.length ? { rules: rules.value } : api.rules()
    ])
    if (id !== request) return
    items.value = append ? items.value.concat(d.items) : d.items
    total.value = d.total
    page.value = next
    ruleStats.value = rs
    rules.value = rl.rules || []
  } catch (e) {
    if (id === request) err.value = e.message
  } finally {
    if (id === request) loading.value = false
  }
}

const ruleName = computed(() => {
  const m = {}
  rules.value.forEach(r => { m[r.id] = r.name })
  return m
})

const sevOrder = { critical: 0, warning: 1, info: 2, unknown: 3 }
const severityLabel = { critical: '严重', warning: '警告', info: '提示', unknown: '未知' }
const sorted = computed(() =>
  [...items.value].sort((a, b) =>
    (sevOrder[a.severity] ?? 9) - (sevOrder[b.severity] ?? 9)))

const groups = computed(() => {
  const result = new Map()
  for (const item of sorted.value) {
    if (!result.has(item.rule_id)) result.set(item.rule_id, [])
    result.get(item.rule_id).push(item)
  }
  return result
})

const highlighted = computed(() => sorted.value[0])
const selectedFinding = computed(() => items.value.find(item => item.id === selectedId.value) || highlighted.value)
const firstRule = computed(() => groups.value.keys().next().value ?? null)

function topSeverity(events) {
  return events.reduce((acc, event) =>
    (sevOrder[event.severity] ?? 9) < (sevOrder[acc] ?? 9) ? event.severity : acc, 'unknown')
}

const EV_LABEL = { confirmed: '已确认', suspected: '疑似', insufficient: '证据不足' }
const EV_CLS = { confirmed: 'ok', suspected: 'warning', insufficient: 'unknown' }

function toggle(id) {
  expanded.value[id] = !expanded.value[id]
  selectedId.value = expanded.value[id] ? id : null
}
function goSession(sid) { if (sid) router.push(`/sessions/${sid}`) }
function goPacket(taskId, num) {
  router.push({ name: 'packets', query: { task: taskId, number: num } })
}

watch([() => store.currentTaskId, sevFilter, ruleFilter], () => load(), { immediate: true })
</script>

<template>
  <div class="page">
    <PageNav
      title="分析结论"
      :sub="`任务 #${store.currentTaskId || '未选择'} · ${loading && !page ? '正在读取诊断' : err && !page ? '诊断读取失败' : `共 ${total} 条诊断`}`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'分析结论'}]">
      <template #actions>
        <AiFocusButton focus="field" label="DeepSeek · 生成排障步骤" />
        <select aria-label="诊断等级" v-model="sevFilter" class="inp sm">
          <option value="">全部等级</option>
          <option value="critical">严重</option>
          <option value="warning">警告</option>
          <option value="info">提示</option>
          <option value="unknown">未知</option>
        </select>
        <select aria-label="诊断规则" v-model="ruleFilter" class="inp sm">
          <option value="">全部规则</option>
          <option v-for="r in rules" :key="r.id" :value="r.id">{{ r.id }} · {{ r.name }}</option>
        </select>
      </template>
    </PageNav>

    <section v-if="store.task?.status === 'completed'" class="diagnostic-overview" aria-label="任务汇总">
      <MetricCard label="报文数" icon="file" :value="store.task.summary?.packet_count" />
      <MetricCard label="业务会话" icon="signal" :value="store.task.summary?.session_count" />
      <MetricCard label="媒体流" icon="wave" :value="store.task.summary?.total_streams" />
      <MetricCard label="诊断事件" icon="warning" :value="ruleStats?.total" />
    </section>
    <div v-if="err" class="err-box" role="alert">{{ err }} <button class="btn" @click="load(page > 0)">重试</button></div>

    <div v-if="!store.currentTaskId" class="card">
      <div class="empty">
        尚未选择分析任务
        <div class="hint">请先在「分析总览」上传抓包文件</div>
      </div>
    </div>

    <template v-else>
      <section v-if="highlighted" v-panel-change="highlighted.id" class="finding" :class="highlighted.severity">
        <div><span>{{ severityLabel[highlighted.severity] }} · 当前结果优先排查</span><h2>{{ highlighted.title }}</h2><p>{{ highlighted.description }}</p></div>
        <button v-if="highlighted.related_packet_ids?.length" class="btn" @click="goPacket(store.currentTaskId, highlighted.related_packet_ids[0])">查看报文 #{{ highlighted.related_packet_ids[0] }}</button>
      </section>
      <div class="findings-layout">
      <!-- 规则命中统计 -->
      <div v-if="ruleStats && ruleStats.total" class="card mb-16">
        <div class="card-head">规则命中统计</div>
        <div class="card-body">
          <div class="stat-grid">
            <div class="stat-item" v-for="(cnt, rid) in ruleStats.by_rule" :key="rid">
              <div class="stat-id mono">{{ rid }}</div>
              <div class="stat-name">{{ ruleName[rid] || '—' }}</div>
              <div class="stat-cnt">{{ cnt }}</div>
            </div>
          </div>
          <div class="ev-row mt-16">
            <span class="ev-label">证据等级分布：</span>
            <span v-for="(cnt, ev) in ruleStats.by_evidence" :key="ev"
                  class="badge" :class="EV_CLS[ev] || 'unknown'">
              {{ EV_LABEL[ev] || ev }} {{ cnt }}
            </span>
          </div>
        </div>
      </div>

      <!-- 诊断列表 -->
      <div class="diag-list">
        <details class="rule-group" v-for="[rule, events] in groups" :key="rule" :open="rule === firstRule">
          <summary>
            <span class="badge" :class="topSeverity(events)">{{ severityLabel[topSeverity(events)] }}</span>
            <b class="mono">{{ rule }}</b>
            <span class="sum-name">{{ ruleName[rule] }}</span>
            <span class="sum-count">{{ events.length }} 条</span>
          </summary>
          <div v-for="d in events" :key="d.id" class="diag-card" :class="d.severity">
            <button class="diag-head" type="button" :aria-expanded="!!expanded[d.id]" @click="toggle(d.id)">
              <span class="badge" :class="d.severity">{{ severityLabel[d.severity] || d.severity }}</span>
              <span class="rule-id mono">{{ d.rule_id }}</span>
              <span class="diag-title">{{ d.title }}</span>
              <span class="spacer"></span>
              <span class="badge" :class="EV_CLS[d.evidence_level] || 'unknown'">
                {{ EV_LABEL[d.evidence_level] || d.evidence_level }}
              </span>
              <span class="toggle"><AppIcon :name="expanded[d.id] ? 'down' : 'next'" /></span>
            </button>

            <div class="diag-body">
              <div class="diag-desc">{{ d.description }}</div>

              <div class="meta-row">
                <span v-if="d.device_id" class="meta-item">
                  设备 <b class="mono">{{ d.device_id }}</b>
                </span>
                <span v-if="d.timestamp != null" class="meta-item">
                  时间 <b class="mono">{{ d.timestamp.toFixed(3) }}s</b>
                </span>
                <button v-if="d.session_id" class="meta-item link" type="button" @click="goSession(d.session_id)">
                  会话 #{{ d.session_id }} <AppIcon name="forward" />
                </button>
              </div>

              <div v-if="expanded[d.id]">
                <div v-if="Object.keys(d.evidence || {}).length" class="block">
                  <div class="block-label">观测证据</div>
                  <pre class="ev-pre">{{ JSON.stringify(d.evidence, null, 2) }}</pre>
                </div>
                <div v-if="d.possible_causes?.length" class="block">
                  <div class="block-label">可能原因</div>
                  <ul><li v-for="(c, i) in d.possible_causes" :key="i">{{ c }}</li></ul>
                </div>
                <div v-if="d.recommendations?.length" class="block">
                  <div class="block-label">建议排查</div>
                  <ul><li v-for="(c, i) in d.recommendations" :key="i">{{ c }}</li></ul>
                </div>
                <div v-if="d.related_packet_ids?.length" class="block">
                  <div class="block-label">关联报文</div>
                  <div class="row" style="gap:6px;flex-wrap:wrap">
                    <button v-for="p in d.related_packet_ids.slice(0, 20)" :key="p"
                       type="button" class="pkt-link mono" @click="goPacket(store.currentTaskId, p)">#{{ p }}</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </details>
      </div>
      <aside v-if="selectedFinding" class="reason-panel card">
        <div class="card-head">所选事件 · 排查依据</div><div class="card-body">
          <h3>{{ selectedFinding.title }}</h3>
          <strong>{{ EV_LABEL[selectedFinding.evidence_level] || '待核实' }} · {{ selectedFinding.rule_id }}</strong>
          <h3>可能原因</h3><ul v-if="selectedFinding.possible_causes?.length"><li v-for="cause in selectedFinding.possible_causes" :key="cause">{{ cause }}</li></ul><p v-else>该规则未提供原因说明。</p>
          <h3>处置建议</h3><ul v-if="selectedFinding.recommendations?.length"><li v-for="action in selectedFinding.recommendations" :key="action">{{ action }}</li></ul><p v-else>请结合关联报文核实。</p>
        </div>
      </aside>
      </div>
      <div v-if="loading" class="empty" role="status">正在读取诊断…</div>
      <button v-else-if="!err && items.length < total" type="button" class="btn" @click="load(true)">
        加载更多（{{ items.length }} / {{ total }}）
      </button>
      <div v-if="!loading && !err && !sorted.length" class="card">
        <div class="empty">
          暂无匹配的诊断
          <div class="hint">当前任务及筛选条件下没有诊断记录</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.finding { --tone:var(--info); display:flex; align-items:center; justify-content:space-between; gap:15px; flex-wrap:wrap; padding:16px; margin-bottom:14px; border-radius:var(--radius); border:1px solid color-mix(in srgb,var(--tone) 30%,var(--line)); border-left:3px solid var(--tone); background:color-mix(in srgb,var(--tone) 8%,var(--surface)); }
.finding.critical { --tone:var(--critical); }.finding.warning { --tone:var(--warning); }
.finding span { color:var(--tone); font-size:12px; font-weight:600; }
.finding h2 { font-size:17px; margin:4px 0; }.finding p,.reason-panel { color:var(--text-2); font-size:13px; }
.findings-layout { display:grid; grid-template-columns:minmax(0,1fr) minmax(210px,28%); gap:12px; align-items:start; }
.findings-layout > .mb-16 { grid-column:1 / -1; margin-bottom:0; }
.reason-panel h3 { font-size:13px; margin:14px 0 5px; color:var(--text); }
.reason-panel ul { padding-left:16px; list-style:disc; }.reason-panel li { margin:5px 0; }
@media(max-width:980px){.findings-layout{grid-template-columns:1fr}}

.stat-grid {
  display: flex; flex-wrap: wrap;
  gap: 0 22px;
  border-top: 1px solid var(--line);
}
.stat-item {
  display: flex; align-items: baseline; gap: 9px;
  flex: 1 1 240px; min-width: 0;
  padding: 8px 0 9px;
  border-bottom: 1px solid var(--line);
}
.stat-id { font-size: 11px; color: var(--text-4); letter-spacing: .02em; flex: none; }
.stat-name { font-size: 12px; color: var(--text-2); line-height: 1.4; flex: 0 1 auto; min-width: 0; }
.stat-cnt {
  font-size: 16px; font-weight: 560; font-family: var(--font-data);
  font-variant-numeric: tabular-nums; color: var(--text);
  flex: none; margin-left: 2px;
}

.ev-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ev-label { font-size: 11.5px; color: var(--text-4); }

.diag-list { display: flex; flex-direction: column; gap: 10px; }
.rule-group > summary {
  list-style: none; display: flex; align-items: center; gap: 8px;
  cursor: pointer; padding: 11px 8px; color: var(--text);
  border-bottom: 1px solid var(--line);
}
.rule-group > summary::-webkit-details-marker { display: none; }
.rule-group > summary:hover { background: var(--surface-2); }
.rule-group > summary::after {
  content: '▸'; color: var(--text-4); font-size: 11px;
  transition: transform var(--dur) var(--ease);
}
.rule-group[open] > summary::after { transform: rotate(90deg); }
.sum-name { font-size: 12.5px; color: var(--text-2); min-width: 0; }
.sum-count { margin-left: auto; color: var(--text-4); font-size: 11.5px; flex: none; }
.rule-group[open] .diag-card { margin-top: 8px; }
.rule-group[open] { padding-bottom: 8px; }
.diag-card {
  background: var(--surface); border: 1px solid var(--line-2);
  border-left: 3px solid var(--line-strong);
  border-radius: 7px; overflow: hidden;
}
.diag-card.critical { border-left-color: var(--critical); }
.diag-card.warning { border-left-color: var(--warning); }
.diag-card.info { border-left-color: var(--info); }

.diag-head {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
  width:100%; border:0; background:transparent; color:var(--text); font:inherit; text-align:left;
  padding: 14px 16px; cursor: pointer;
}
.diag-head:hover { background: var(--surface-2); }
.rule-id { font-size: 11px; color: var(--text-4); }
.diag-title { font-size: 13px; font-weight: 550; }
.toggle { color: var(--text-4); font-size: 11px; width: 12px; text-align: center; }

.diag-body { padding: 0 16px 16px; }
.diag-desc { font-size: 12.5px; color: var(--text-2); line-height: 1.7; max-width: 104ch; }

.meta-row {
  display: flex; gap: 16px; flex-wrap: wrap; margin-top: 9px;
  font-size: 11.5px; color: var(--text-4);
}
.meta-item b { color: var(--text-2); font-weight: 500; }
.meta-item.link { color: var(--brand-lt); cursor: pointer; background:none; border:0; padding:0; font:inherit; text-decoration: underline; text-underline-offset: 2px; }
.meta-item.link:hover { text-decoration-color: currentColor; }

.block { margin-top: 12px; }
.block-label { font-size: 11.5px; color: var(--text-4); margin-bottom: 4px; }
.block ul { margin-left: 18px; font-size: 12.5px; color: var(--text-2); line-height: 1.75; }
.ev-pre {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 10px 12px;
  font-family: var(--font-mono); font-size: 11.5px; color: var(--text-2);
  max-height: 220px; overflow: auto; line-height: 1.6;
}
.pkt-link {
  font-family: var(--font-mono); font-size: 11.5px; padding: 1px 4px;
  color: var(--brand-lt); cursor: pointer; background:transparent; border:0;
  border-bottom: 1px solid var(--line-2);
}
.pkt-link:hover { color: var(--text); border-bottom-color: currentColor; }
.err-box {
  background: var(--critical-soft); border-left: 2px solid var(--critical);
  border-radius: 0; padding: 10px 12px; font-size: 12.5px;
  color: var(--critical); margin-bottom: 14px;
}
.diagnostic-overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:var(--space-3); margin-bottom:var(--space-4); }
.reason-panel { position:sticky; top:12px; }
@media(max-width:980px) { .reason-panel { position:static; } }
</style>
