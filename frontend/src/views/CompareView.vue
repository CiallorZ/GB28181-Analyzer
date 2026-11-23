<script setup>
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
function create() {
  run(async () => {
    const data = await api.compare(form.value)
    await router.push('/compare/'+data.id)
  })
}
</script>
<template><main class="page"><h1>双抓包对比</h1><p>选择同一路视频的两个已完成任务，核对两侧观察到的信令和媒体结果。</p>
<form class="card card-body" @submit.prevent="create"><div class="g2">
<fieldset v-for="side in ['a','b']" :key="side"><legend>{{side.toUpperCase()}} 侧抓包</legend>
<label>已完成任务<select v-model="form['task_'+side+'_id']" required><option disabled :value="null">选择任务</option><option v-for="t in tasks" :key="t.id" :value="t.id" :disabled="form[side==='a'?'task_b_id':'task_a_id']===t.id">#{{t.id}} {{t.name}}</option></select></label>
<label>侧别标签（可选）<input maxlength="100" v-model="form['label_'+side]" :placeholder="side==='a'?'例如：设备侧':'例如：平台侧'"></label></fieldset></div>
<p v-if="busy" role="status">正在读取数据…</p><p v-else-if="tasks.length<2">请先完成两个抓包任务。</p>
<button class="btn primary" :disabled="busy || !form.task_a_id || !form.task_b_id">创建对比快照</button></form>
<p v-if="error" class="err-box" role="alert">{{error}}</p><h2>已保存的对比</h2><p v-if="!busy && !history.length">暂无对比快照</p>
<p class="history" v-for="h in history" :key="h.id"><router-link :to="'/compare/'+h.id">对比 #{{h.id}} · {{h.label_a || 'A'}} #{{h.task_a_id}} / {{h.label_b || 'B'}} #{{h.task_b_id}}</router-link> {{h.created_at}}</p>
<button class="btn" v-if="history.length<total" :disabled="busy" @click="run(more)">更多快照</button></main></template>
<style scoped>
.page { max-width:1240px; }
fieldset { border:1px solid var(--line); border-radius:var(--radius-lg); padding:14px 18px; min-width:0; }
legend { padding:0 6px; color:var(--brand-lt); font-weight:600; }
label { display:grid; gap:6px; margin:8px 0; color:var(--text-2); }
select,input { width:100%; padding:9px; background:var(--surface); color:var(--text); border:1px solid var(--line-2); border-radius:6px; }
form,h2 { margin:16px 0; }
form button { margin-top:14px; }
.history { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; padding:10px 0; border-bottom:1px solid var(--line); color:var(--text-3); }
</style>
