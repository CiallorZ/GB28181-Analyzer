<script setup>
import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { allowedLink, fieldName, formatValue, groups, judgments } from '../utils/compare'

const route = useRoute()
const router = useRouter()
const data = shallowRef(null)
const error = ref('')
const loading = ref(false)
const onlyDiff = ref(false)
const tab = ref(0)
const page = ref(1)
const sides = ['a', 'b']
const layerNames = { sessions: '会话', streams: '媒体流', diagnostics: '诊断事件' }
const badgeStyle = { same: 'ok', different: 'warning', only_a: 'info', only_b: 'info', ambiguous: 'warning', unknown: 'unknown' }
const visible = computed(() => {
  if (!data.value) return []
  const [, layer, accept] = groups[tab.value]
  return data.value.result[layer].map(row => ({
    ...row,
    cells: Object.entries(row.fields).filter(([field, cell]) => accept(field) && (!onlyDiff.value || cell[2] !== 'same'))
  })).filter(row => row.cells.length)
})
const pageRows = computed(() => visible.value.slice((page.value - 1) * 10, page.value * 10))
watch([tab, onlyDiff], () => { page.value = 1 })
watch(() => route.params.id, async (id, _, cleanup) => {
  let active = true
  cleanup(() => { active = false })
  loading.value = true
  error.value = ''
  data.value = null
  page.value = 1
  try {
    const value = await api.comparison(id)
    if (active) data.value = value
  } catch (e) {
    if (active) error.value = e.message
  } finally {
    if (active) loading.value = false
  }
}, { immediate: true })

function reason(side, id) {
  if (data.value.stale) return '快照已过期'
  return allowedLink(data.value, side, id) ? '' : '目标记录不可用'
}
async function jump(side, session = null) {
  const id = data.value.id
  try {
    const fresh = await api.comparison(id)
    if (data.value?.id !== id) return
    data.value = fresh
    if (!allowedLink(fresh, side, session)) return
    await router.push(session == null
      ? { path: '/packets', query: { task: fresh['task_' + side + '_id'] } }
      : '/sessions/' + session)
  } catch (e) {
    if (data.value?.id === id) error.value = e.message
  }
}
function identifiers(values) {
  return Object.entries(values).map(([key, value]) => fieldName(key) + ' ' + formatValue(Array.isArray(value) ? value.join('、') : value, key)).join(' · ')
}
</script>

<template>
  <main class="page comparison">
    <router-link to="/compare">‹ 返回双抓包对比</router-link>
    <header class="row-between wrapx">
      <h1>对比快照 #{{ route.params.id }}</h1>
      <div v-if="data" class="row wrapx">
        <a v-for="fmt in ['md','json']" :key="fmt" class="btn" download
           :href="'/api/v1/comparisons/'+data.id+'/report?format='+fmt">导出 .{{ fmt }}</a>
      </div>
    </header>
    <p v-if="loading" role="status">正在读取快照…</p>
    <p v-if="error" class="err-box" role="alert">{{ error }}</p>
    <template v-if="data">
      <p v-if="data.stale" class="err-box" role="status">输入任务已变化。当前显示已保存的快照，原始证据跳转已禁用。</p>
      <div class="g2">
        <section v-for="side in sides" :key="side" class="card card-body">
          <div class="row"><b class="side">{{ side.toUpperCase() }}</b><h2>{{ data['label_'+side] || '抓包任务' }} #{{ data['task_'+side+'_id'] }}</h2></div>
          <p v-for="(f,i) in data.fingerprint[side].files" :key="i">{{ f.filename }}</p>
          <p class="meta">完成时间（UTC） {{ formatValue(data.fingerprint[side].completed_at) }} · {{ data.fingerprint[side].sessions }} 个会话 · {{ data.fingerprint[side].streams }} 条流</p>
          <button class="btn" :disabled="!!reason(side,null)" @click="jump(side)">查看报文</button> <small>{{ reason(side,null) }}</small>
        </section>
      </div>
      <section class="card card-body">
        <h2>对齐摘要</h2>
        <p>已对齐 <b>{{ data.summary.aligned_sessions }}</b> 个会话、<b>{{ data.summary.aligned_streams }}</b> 条流。
          结构或精确值差异 {{ data.summary.structural }} 项，超出对比容差 {{ data.summary.beyond_tolerance }} 项，无法比较 {{ data.summary.unknown }} 项。</p>
        <p class="meta">{{ data.result.methods }}</p>
        <p v-if="data.result.truncated">明细已截断。全量对齐会话 {{ data.result.totals.sessions }}、媒体流 {{ data.result.totals.streams }}、诊断规则 {{ data.result.totals.diagnostics }}。</p>
      </section>
      <div class="row-between wrapx">
        <nav class="row wrapx" aria-label="对比层面"><button v-for="([name],i) in groups" :key="name" class="btn"
          :aria-pressed="tab===i" @click="tab=i">{{ name }}</button></nav>
        <label><input type="checkbox" v-model="onlyDiff"> 只看差异（含未知）</label>
      </div>
      <p v-if="!visible.length" class="card card-body">当前分区没有符合条件的记录。</p>
      <article class="card" v-for="r in pageRows" :key="r.rule_id || r.a">
        <div class="card-body">
          <div class="row wrapx">
            <h3>{{ r.rule_id || ('A #'+r.a+' / B #'+r.b) }}</h3>
            <span class="badge" :class="r.confidence==='low'?'warning':'info'">
              {{ r.confidence==='low'?'低置信度推断':r.method?'精确对齐':'规则编号对齐' }}
            </span>
          </div>
          <p v-if="r.evidence" class="meta">{{ identifiers(r.evidence) }}</p>
          <div v-if="r.method" class="row wrapx">
            <span v-for="side in sides" :key="side">
              <button class="btn xs" :disabled="!!reason(side,r['session_'+side])" @click="jump(side,r['session_'+side])">
                {{ side.toUpperCase() }} 侧会话
              </button> <small>{{ reason(side,r['session_'+side]) }}</small>
            </span>
          </div>
        </div>
        <div class="scroll"><table class="tbl">
          <thead><tr><th>字段</th><th>A 侧</th><th>B 侧</th><th>判定</th></tr></thead>
          <tbody><tr v-for="[k,[a,b,status]] in r.cells" :key="k">
            <th scope="row">{{ fieldName(k) }}</th><td>{{ formatValue(a,k) }}</td><td>{{ formatValue(b,k) }}</td>
            <td><span class="badge" :class="badgeStyle[status]">{{ status==='different' && k in data.result.tolerances ? '超出对比容差' : judgments[status] }}</span></td>
          </tr></tbody>
        </table></div>
      </article>
      <div v-if="visible.length>10" class="row">
        <button class="btn" :disabled="page===1" @click="page--">上一页</button>{{ page }} / {{ Math.ceil(visible.length/10) }}
        <button class="btn" :disabled="page*10>=visible.length" @click="page++">下一页</button>
      </div>
      <details class="card card-body">
        <summary>未对齐项 · {{ data.summary.unaligned }} 条（不计入差异汇总）</summary>
        <p v-if="!data.summary.unaligned">没有未对齐记录。</p>
        <p v-if="data.result.unmatched.length<data.summary.unaligned">当前保留 {{ data.result.unmatched.length }} 条未对齐明细。</p>
        <p v-for="r in data.result.unmatched" :key="[r.layer,r.side,r.id].join('-')">
          {{ layerNames[r.layer] }} · {{ r.side.toUpperCase() }} #{{ r.id }} <span class="badge" :class="badgeStyle[r.status]">{{ judgments[r.status] }}</span>
          <small>{{ identifiers(r.observed) }}</small>
        </p>
      </details>
      <footer class="meta"><p v-for="note in data.result.limitations" :key="note">{{ note }}</p></footer>
    </template>
  </main>
</template>

<style scoped>
.comparison { display:grid; grid-template-columns:minmax(0,1fr); gap:16px; }
h1,h2,h3 { margin:0; }
h2 { font-size:17px; } h3 { font-size:15px; }
.side { font:600 17px var(--font-mono); border-inline-start:3px solid var(--brand); padding-inline-start:10px; }
.card { overflow-wrap:anywhere; }
.card p { margin:9px 0; }
.meta,small { color:var(--text-3); }
[aria-pressed=true] { border-color:var(--brand); color:var(--brand-lt); background:var(--brand-soft); }
.scroll { overflow:auto; }
table { min-width:460px; }
th,td { text-align:left; }
summary { cursor:pointer; }
</style>
