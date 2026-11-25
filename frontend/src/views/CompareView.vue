<script setup>
import PageNav from '../components/PageNav.vue'
import AppIcon from '../components/AppIcon.vue'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'

const router = useRouter()
const tasks = ref([]), history = ref([]), form = ref({task_a_id:null,task_b_id:null,label_a:'',label_b:''})
const busy = ref(false), error = ref(''), total = ref(0)

async function more() {
  const data = await api.comparisons(history.value.length)
  total.value = data.total
  history.value.push(...data.items)
}

async function run(fn) {
  busy.value = true
  error.value = ''
  try { await fn() } catch(e) { error.value = e.message } finally { busy.value = false }
}

onMounted(() => run(async () => {
  let page = 1
  while (true) {
    const data = await api.tasks({status:'completed',page:page++,page_size:100})
    tasks.value.push(...data.items)
    if (!data.items.length || tasks.value.length >= data.total) break
  }
  await more()
}))

function localTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN')
}

function create() {
  run(async () => {
    const data = await api.compare(form.value)
    await router.push('/compare/'+data.id)
  })
}
</script>

<template>
  <main class="page">
    <PageNav
      title="双抓包对比"
      sub="选择同一路视频的两个已完成任务，核对两侧观察到的信令和媒体结果。"
      :crumbs="[{label:'工作台', to:'/'}, {label:'双抓包对比'}]" />

    <form class="card mb-16" @submit.prevent="create">
      <div class="card-head">
        选择两个已完成的任务
        <span class="count-badge">同一路视频 · 两侧抓包</span>
      </div>
      <div class="card-body">
        <div class="g2">
          <fieldset v-for="side in ['a','b']" :key="side">
            <legend>{{ side.toUpperCase() }} 侧抓包</legend>
            <label>
              <span>已完成任务</span>
              <select class="inp" v-model="form['task_'+side+'_id']" required>
                <option disabled :value="null">选择任务</option>
                <option v-for="t in tasks" :key="t.id" :value="t.id"
                        :disabled="form[side==='a'?'task_b_id':'task_a_id']===t.id">
                  #{{ t.id }} {{ t.name }}
                </option>
              </select>
            </label>
            <label>
              <span>侧别标签（可选）</span>
              <input class="inp" maxlength="100" v-model="form['label_'+side]"
                     :placeholder="side==='a' ? '例如：设备侧' : '例如：平台侧'" />
            </label>
          </fieldset>
        </div>

        <p v-if="busy" class="hint" role="status">正在读取数据…</p>
        <p v-else-if="tasks.length < 2" class="hint">至少需要两个已完成的任务才能创建对比。</p>
        <p v-if="error" class="err-box" role="alert">{{ error }}</p>

        <div class="form-actions">
          <button class="btn primary" :disabled="busy || !form.task_a_id || !form.task_b_id">
            创建对比快照
          </button>
          <span class="hint">只读取两侧已有的分析结论，不会重新分析抓包。</span>
        </div>
      </div>
    </form>

    <section class="card">
      <div class="card-head">
        已保存的对比
        <span class="count-badge">{{ total }} 个</span>
      </div>
      <div class="card-body tight">
        <div v-if="!busy && !history.length" class="empty">
          暂无对比快照
          <div class="hint">选择两个已完成的任务创建对比，即可并排核对信令与媒体指标。</div>
        </div>
        <ul v-else class="history-list">
          <li v-for="h in history" :key="h.id">
            <router-link :to="'/compare/' + h.id">
              <span class="h-id">对比 #{{ h.id }}</span>
              <span class="h-pair">
                {{ h.label_a || 'A' }} #{{ h.task_a_id }} ↔ {{ h.label_b || 'B' }} #{{ h.task_b_id }}
              </span>
              <time :datetime="h.created_at">{{ localTime(h.created_at) }}</time>
              <AppIcon name="forward" />
            </router-link>
          </li>
        </ul>
      </div>
    </section>

    <button class="btn mt-14" v-if="history.length < total" :disabled="busy" @click="run(more)">
      加载更多
    </button>
  </main>
</template>

<style scoped>
.page { max-width: 1240px; }
fieldset {
  border: 1px solid var(--line); border-radius: var(--radius);
  padding: 12px 14px; min-width: 0; margin: 0;
}
legend { padding: 0 6px; color: var(--text-3); font-size: 11.5px; font-weight: 600; letter-spacing: .02em; }
label { display: grid; gap: 6px; font-size: 12px; color: var(--text-2); margin-bottom: 10px; }
label:last-child { margin-bottom: 0; }
label .inp { width: 100%; }
.form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.card-body > .hint { margin-top: 10px; }
.count-badge {
  font-size: 11px; padding: 1px 7px; border-radius: 99px;
  background: var(--panel-3); color: var(--text-3);
}
.history-list { list-style: none; margin: 0; padding: 0; }
.history-list li { border-bottom: 1px solid var(--line); }
.history-list li:last-child { border-bottom: 0; }
.history-list a {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 16px; color: var(--text); text-decoration: none;
  font-size: 12.5px; transition: background-color var(--dur) var(--ease);
}
.history-list a:hover { background: var(--surface-2); }
.h-id { font-weight: 600; flex: none; }
.h-pair { color: var(--text-2); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-list time { margin-left: auto; color: var(--text-4); font-size: 11.5px; flex: none; }
.history-list :deep(svg) { width: 14px; height: 14px; color: var(--text-4); flex: none; }
@media (max-width: 560px) {
  .history-list a { flex-wrap: wrap; gap: 4px 10px; }
  .history-list time { margin-left: 0; }
}
.err-box {
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 10px 12px; font-size: 12.5px;
  color: var(--critical); margin-top: 12px;
}
</style>

