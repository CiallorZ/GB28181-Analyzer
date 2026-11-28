<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'
import InterfaceState from '../components/InterfaceState.vue'
import { feedback } from '../stores/interface'
import { useTaskStore } from '../stores/task'
import { clearAll, clearTask } from '../utils/taskCache'

const router = useRouter()
const route = useRoute()
const store = useTaskStore()
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const pageRevision = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const loading = ref(true)
const err = ref('')
const storage = ref(null)
const purging = ref(false)
const purgeMsg = ref('')

async function loadStorage() {
  try { storage.value = await api.storageUsage() } catch { storage.value = null }
}

async function purge(keep) {
  const message = keep === 0
    ? '将删除所有已完成任务的上传抓包、报文索引和重建视频，只保留任务记录与统计数据；分析中的任务不受影响。此操作不可撤销，继续？'
    : `将按当前保留策略清理上传抓包、报文索引和重建视频，最多保留最近 ${keep} 个任务的这些文件，其他任务只保留记录与统计数据。此操作不可撤销，继续？`
  if (!confirm(message)) return
  purging.value = true
  purgeMsg.value = ''
  try {
    const r = await api.storagePurge(keep)
    const actions = r.actions || []
    for (const action of actions) clearTask(action.task_id)
    const currentPurged = actions.some(action => action.task_id === store.currentTaskId)
    const reloadCurrent = currentPurged
      ? store.loadTask(store.currentTaskId).catch(() => {})
      : Promise.resolve()
    purgeMsg.value = `已清理 ${actions.length} 个任务，当前占用 ${r.usage?.total_mb ?? 0} MB`
    await Promise.all([load(), loadStorage(), reloadCurrent])
  } catch (e) {
    purgeMsg.value = '清理失败：' + e.message
  } finally {
    purging.value = false
  }
}

async function purgeAll() {
  if (!confirm('将删除所有可清理任务的上传抓包、报文索引和重建视频，只保留任务记录与统计数据；分析中的任务不受影响。此操作不可撤销，继续？')) return
  purging.value = true
  purgeMsg.value = ''
  try {
    const r = await api.storagePurgeAll()
    clearAll()
    const reloadCurrent = store.currentTaskId
      ? store.loadTask(store.currentTaskId).catch(() => {})
      : Promise.resolve()
    purgeMsg.value = `已清空 ${r.tasks} 个任务的任务文件，释放 ${r.freed_mb} MB`
    await Promise.all([load(), loadStorage(), reloadCurrent])
  } catch (e) {
    purgeMsg.value = '清空失败：' + e.message
  } finally {
    purging.value = false
  }
}

const STATUS_LABEL = {
  pending: '待分析', analyzing: '分析中', completed: '已完成',
  failed: '失败', cancelled: '已取消'
}

let request = 0
async function load() {
  const seq = ++request
  err.value = ''
  loading.value = true
  try {
    const r = await api.tasks({
      page: page.value, page_size: pageSize,
      status: statusFilter.value || undefined,
      keyword: keyword.value || undefined
    })
    if (seq !== request) return
    list.value = r.items
    pageRevision.value++
    total.value = r.total
  } catch (e) { if (seq === request) err.value = e.message }
  finally { if (seq === request) loading.value = false }
}

async function openTask(t) {
  router.push(`/tasks/${t.id}`)
}

async function reanalyze(t) {
  try {
    await api.analyze(t.id)
    clearTask(t.id)          // 旧版本结果不会再被命中，直接释放
    feedback('confirm')
    await load()
  } catch (e) { feedback('error'); err.value = e.message }
}

async function removeTask(t) {
  if (!confirm(`确定删除任务「${t.name}」？文件与分析结果都会删除。`)) return
  try {
    await api.deleteTask(t.id)
    clearTask(t.id)
    if (store.currentTaskId === t.id) store.setCurrent(null)
    await load()
  } catch (e) { err.value = e.message }
}

function fmtSize(b) {
  if (!b) return '—'
  const u = ['B', 'KB', 'MB', 'GB']; let i = 0, n = b
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return (i ? n.toFixed(1) : n) + ' ' + u[i]
}

async function filter(nextPage) {
  const query = { ...route.query, keyword: keyword.value || undefined,
    status: statusFilter.value || undefined, page: nextPage > 1 ? nextPage : undefined }
  if (router.resolve({ query }).fullPath === route.fullPath) await load()
  else await router.replace({ query })
}
watch(() => route.fullPath, () => {
  if (route.name !== 'tasks') return
  keyword.value = String(route.query.keyword || '')
  statusFilter.value = String(route.query.status || '')
  const n = Number(route.query.page)
  page.value = Number.isSafeInteger(n) && n > 0 ? n : 1
  load()
}, { immediate: true })
onMounted(loadStorage)
</script>

<template>
  <div class="page">
    <PageNav
      title="分析任务"
      :sub="`共 ${total} 个任务`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'分析任务'}]">
      <template #actions>
        <input v-model="keyword" class="inp sm" placeholder="搜索文件名" aria-label="搜索抓包文件名" @keyup.enter="filter(1)" />
        <select v-model="statusFilter" aria-label="任务状态" class="inp sm" @change="filter(1)">
          <option value="">全部状态</option>
          <option value="completed">已完成</option>
          <option value="analyzing">分析中</option>
          <option value="failed">失败</option>
          <option value="pending">待分析</option>
          <option value="cancelled">已取消</option>
        </select>
        <button class="btn sm" @click="filter(1)">刷新</button>
      </template>
    </PageNav>

    <InterfaceState v-if="err" class="card task-error" kind="error" title="任务请求失败" :detail="err">
      <button class="btn sm" type="button" @click="load">刷新列表</button>
    </InterfaceState>

    <!-- 存储管理 -->
    <div v-if="storage" class="storage-card glass-panel">
      <div class="sc-left">
        <div class="sc-icon">
          <AppIcon name="storage" />
        </div>
        <div class="sc-info">
          <div class="sc-title">
            存储占用 <b>{{ storage.usage.total_mb }} MB</b>
          </div>
          <div class="sc-detail mono-sm">
            上传 {{ storage.usage.uploads_mb }} MB ·
            视频 {{ storage.usage.rebuilt_mb }} MB ·
            数据库 {{ storage.usage.db_mb }} MB
          </div>
          <meter v-if="storage.policy.disk_budget_mb > 0" class="storage-meter" min="0" :max="storage.policy.disk_budget_mb" :value="storage.usage.total_mb" aria-label="存储预算使用量"></meter>
          <div class="sc-policy">
            保留最近 <b>{{ storage.policy.keep_tasks }}</b> 个任务 ·
            <b>{{ storage.policy.keep_days }}</b> 天 ·
            上限 <b>{{ storage.policy.disk_budget_mb }}</b> MB
            <span v-if="storage.policy.keep_tasks === 0" class="badge warning"
                  style="margin-left:8px">不保留历史</span>
          </div>
        </div>
      </div>
      <div class="sc-acts">
        <button class="btn sm" :disabled="purging" @click="purge(5)">
          只留最近 5 个
        </button>
        <button class="btn sm" :disabled="purging" @click="purge(0)">
          清空所有任务文件
        </button>
        <button class="btn sm danger" :disabled="purging" @click="purgeAll">
          彻底清理
        </button>
      </div>
      <div v-if="purgeMsg" class="sc-msg" role="status">{{ purgeMsg }}</div>
    </div>

    <div class="card task-list" :aria-busy="loading">
      <div v-if="list.length" class="table-scroll">
        <table class="tbl clickable" aria-label="分析任务">
          <thead>
            <tr>
              <th>ID</th><th>文件名</th><th>状态</th><th>报文</th>
              <th>大小</th><th>会话</th><th>异常</th><th>创建时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody :key="pageRevision" class="page-content-in">
            <tr v-for="t in list" :key="t.id" tabindex="0" @click="openTask(t)" @keydown.enter.self="openTask(t)">
              <td class="mono">#{{ t.id }}</td>
              <td class="task-name"><span class="task-file"><AppIcon name="file" /><span class="truncate" :title="t.name">{{ t.name }}</span></span></td>
              <td>
                <span class="badge" :class="{
                  ok: t.status === 'completed',
                  accent: t.status === 'analyzing',
                  critical: t.status === 'failed',
                  unknown: t.status === 'pending' || t.status === 'cancelled'
                }">{{ STATUS_LABEL[t.status] }}</span>
                <span v-if="t.status === 'analyzing'" class="mono-sm" style="margin-left:6px">{{ t.progress }}%</span>
              </td>
              <td class="num">{{ t.packet_count ?? '—' }}</td>
              <td class="num">{{ fmtSize(t.file_size) }}</td>
              <td class="num">{{ t.session_count ?? '—' }}</td>
              <td class="num" :class="t.diagnostic_count ? 'text-warning' : ''">
                {{ t.diagnostic_count ?? '—' }}
              </td>
              <td class="mono-sm">{{ new Date(t.created_at).toLocaleString('zh-CN') }}</td>
              <td @click.stop>
                <button class="btn-mini" @click="reanalyze(t)">重分析</button>
                <button class="btn-mini danger" @click="removeTask(t)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <InterfaceState v-else-if="loading" kind="loading" title="正在读取分析任务…" />
      <InterfaceState v-else-if="!err" :title="keyword || statusFilter ? '没有匹配的任务' : '还没有分析任务'"
        :detail="keyword || statusFilter ? '清除筛选可以恢复全部任务。' : '选择抓包文件即可开始。'" icon="history">
        <button v-if="keyword || statusFilter" type="button" class="btn sm" @click="keyword = ''; statusFilter = ''; filter(1)">清除筛选</button>
        <router-link v-else to="/" class="btn primary sm">导入抓包</router-link>
      </InterfaceState>
    </div>

    <div class="row mt-16" style="justify-content:flex-end">
      <button class="btn" :disabled="page <= 1" @click="filter(page - 1)">上一页</button>
      <span class="mono-sm">{{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
      <button class="btn" :disabled="page >= Math.ceil(total / pageSize)" @click="filter(page + 1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.inp {
  height: 30px; padding: 0 10px; background: var(--bg-2);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text); font-size: 12.5px; font-family: inherit;
}
.inp:focus { outline: none; border-color: var(--accent); }
.storage-card {
  display: flex; align-items: center; gap: 16px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 16px;
}
.sc-left { display:flex; align-items:center; gap:13px; flex:1 1 230px; min-width:0; }
.task-list .table-scroll { overflow:auto; }
.task-list table { min-width:690px; }
.task-name { max-width:245px; }
.task-file { display:flex; align-items:center; gap:8px; min-width:0; font-weight:650; }
.task-file .app-icon { color:var(--brand-lt); }
.task-error { margin-bottom:var(--ui-gap); }
.task-list tr:focus-visible { outline-offset:-2px; }
.sc-icon {
  width: 38px; height: 38px; flex: none;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-3);
}
.sc-icon svg { width: 17px; height: 17px; }
.sc-info { min-width: 0; }
.sc-title { font-size: 13px; color: var(--text-2); }
.sc-title b { color: var(--text); font-size: 15px; font-weight: 680; }
.sc-detail { margin-top: 3px; }
.sc-policy { font-size: 11.5px; color: var(--text-4); margin-top: 4px; }
.sc-policy b { color: var(--text-3); font-weight: 600; }
.sc-acts { display: flex; gap: 7px; flex-wrap: wrap; }
.sc-msg {
  width: 100%; font-size: 12px; color: var(--ok);
  padding-top: 10px; border-top: 1px dashed var(--line);
}

 .task-list .tbl th { position:sticky; top:0; z-index:1; }
.task-list .tbl td { height:36px; }
.task-list .tbl th { white-space:nowrap; }
.storage-meter { display:block; width:min(300px,100%); height:9px; margin:6px 0; }
.storage-meter::-webkit-meter-bar { background:var(--line); border:0; }
.storage-meter::-webkit-meter-optimum-value { background:var(--brand); border-radius:6px; }
</style>
