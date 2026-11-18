<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
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

async function load() {
  if (!store.currentTaskId) return
  try {
    const [d, rs, rl] = await Promise.all([
      api.diagnostics(store.currentTaskId, {
        page_size: 200,
        severity: sevFilter.value || undefined,
        rule_id: ruleFilter.value || undefined
      }),
      api.ruleStats(store.currentTaskId),
      api.rules()
    ])
    items.value = d.items
    ruleStats.value = rs
    rules.value = rl.rules || []
  } catch (e) { err.value = e.message }
}

const ruleName = computed(() => {
  const m = {}
  rules.value.forEach(r => { m[r.id] = r.name })
  return m
})

const sevOrder = { critical: 0, warning: 1, info: 2, unknown: 3 }
const sorted = computed(() =>
  [...items.value].sort((a, b) =>
    (sevOrder[a.severity] ?? 9) - (sevOrder[b.severity] ?? 9)))

const EV_LABEL = { confirmed: '已确认', suspected: '疑似', insufficient: '证据不足' }
const EV_CLS = { confirmed: 'ok', suspected: 'warning', insufficient: 'unknown' }

function toggle(id) { expanded.value[id] = !expanded.value[id] }
function goSession(sid) { if (sid) router.push(`/sessions/${sid}`) }
function goPacket(taskId, num) {
  router.push({ name: 'packets', query: { task: taskId, number: num } })
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageNav
      title="智能故障诊断"
      :sub="`任务 #${store.currentTaskId || '未选择'} · 共 ${items.length} 条诊断`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'智能故障诊断'}]">
      <template #actions>
        <select v-model="sevFilter" class="inp sm" @change="load()">
          <option value="">全部等级</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
          <option value="unknown">Unknown</option>
        </select>
        <select v-model="ruleFilter" class="inp sm" @change="load()">
          <option value="">全部规则</option>
          <option v-for="r in rules" :key="r.id" :value="r.id">{{ r.id }} · {{ r.name }}</option>
        </select>
      </template>
    </PageNav>

    <div v-if="err" class="err-box">{{ err }}</div>

    <div v-if="!store.currentTaskId" class="card">
      <div class="empty">
        尚未选择分析任务
        <div class="hint">请先在「分析总览」上传抓包文件</div>
      </div>
    </div>

    <template v-else>
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
        <div v-for="d in sorted" :key="d.id" class="diag-card" :class="d.severity">
          <div class="diag-head" @click="toggle(d.id)">
            <span class="badge" :class="d.severity">{{ d.severity }}</span>
            <span class="rule-id mono">{{ d.rule_id }}</span>
            <span class="diag-title">{{ d.title }}</span>
            <span class="spacer"></span>
            <span class="badge" :class="EV_CLS[d.evidence_level] || 'unknown'">
              {{ EV_LABEL[d.evidence_level] || d.evidence_level }}
            </span>
            <span class="toggle">{{ expanded[d.id] ? '▾' : '▸' }}</span>
          </div>

          <div class="diag-body">
            <div class="diag-desc">{{ d.description }}</div>

            <div class="meta-row">
              <span v-if="d.device_id" class="meta-item">
                设备 <b class="mono">{{ d.device_id }}</b>
              </span>
              <span v-if="d.timestamp != null" class="meta-item">
                时间 <b class="mono">{{ d.timestamp.toFixed(3) }}s</b>
              </span>
              <span v-if="d.session_id" class="meta-item link" @click="goSession(d.session_id)">
                会话 #{{ d.session_id }} →
              </span>
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
                  <a v-for="p in d.related_packet_ids.slice(0, 20)" :key="p"
                     class="pkt-link mono" @click="goPacket(store.currentTaskId, p)">#{{ p }}</a>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!sorted.length" class="card">
        <div class="empty">
          未发现异常
          <div class="hint">规则引擎未在该任务中检测到问题</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.h1 { font-size: 20px; font-weight: 600; }
.sub { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.inp {
  height: 30px; padding: 0 10px; background: var(--bg-2);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text); font-size: 12.5px; font-family: inherit;
}
.inp:focus { outline: none; border-color: var(--accent); }

.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.stat-item {
  background: var(--panel-2); border-radius: var(--radius-sm);
  padding: 10px 12px; border-left: 2px solid var(--accent);
}
.stat-id { font-size: 12px; color: var(--accent); }
.stat-name { font-size: 12px; color: var(--text-2); margin: 3px 0; }
.stat-cnt { font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; }

.ev-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ev-label { font-size: 12px; color: var(--text-3); }

.diag-list { display: flex; flex-direction: column; gap: 12px; }
.diag-card {
  background: var(--panel); border: 1px solid var(--border);
  border-left: 3px solid var(--text-4);
  border-radius: var(--radius); overflow: hidden;
}
.diag-card.critical { border-left-color: var(--critical); }
.diag-card.warning { border-left-color: var(--warning); }
.diag-card.info { border-left-color: var(--info); }

.diag-head {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 16px; cursor: pointer;
  background: var(--panel-2);
}
.diag-head:hover { background: var(--panel-3); }
.rule-id { font-size: 12px; color: var(--text-3); }
.diag-title { font-size: 13px; font-weight: 600; }
.toggle { color: var(--text-4); font-size: 11.5px; }

.diag-body { padding: 13px 16px; }
.diag-desc { font-size: 12.5px; color: var(--text-2); line-height: 1.75; }

.meta-row {
  display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px;
  font-size: 12px; color: var(--text-3);
}
.meta-item b { color: var(--text-2); font-weight: 500; }
.meta-item.link { color: var(--accent); cursor: pointer; }
.meta-item.link:hover { text-decoration: underline; }

.block { margin-top: 12px; }
.block-label {
  font-size: 12px; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .5px; margin-bottom: 5px;
}
.block ul { margin-left: 18px; font-size: 12.5px; color: var(--text-2); line-height: 1.8; }
.ev-pre {
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 12px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-2);
  max-height: 220px; overflow: auto; line-height: 1.6;
}
.pkt-link {
  font-size: 12px; padding: 1px 7px; border-radius: 3px;
  background: var(--accent-bg); color: var(--accent); cursor: pointer;
}
.err-box {
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 12px 14px; font-size: 13px;
  color: var(--critical); margin-bottom: 14px;
}
</style>
