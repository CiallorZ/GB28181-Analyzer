<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'
import { useTaskStore } from '../stores/task'

const router = useRouter()
const store = useTaskStore()
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const statusFilter = ref('')
const loading = ref(false)
const err = ref('')
const storage = ref(null)
const purging = ref(false)
const purgeMsg = ref('')

async function loadStorage() {
  try { storage.value = await api.storageUsage() } catch { storage.value = null }
}

async function purge(keep) {
  purging.value = true
  purgeMsg.value = ''
  try {
    const r = await api.storagePurge(keep)
    purgeMsg.value = `已清理 ${r.actions?.length || 0} 个任务，释放 ${r.usage?.total_mb ?? 0} MB 占用`
    await Promise.all([load(), loadStorage()])
  } catch (e) {
    purgeMsg.value = '清理失败：' + e.message
  } finally {
    purging.value = false
  }
}

async function purgeAll() {
  if (!confirm('将删除所有任务的上传文件与视频，只保留统计数据。继续？')) return
  purging.value = true
  purgeMsg.value = ''
  try {
    const r = await api.storagePurgeAll()
    purgeMsg.value = `已清空 ${r.tasks} 个任务的媒体文件，释放 ${r.freed_mb} MB`
    await Promise.all([load(), loadStorage()])
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

async function load() {
  loading.value = true
  try {
    const r = await api.tasks({
      page: page.value, page_size: pageSize,
      status: statusFilter.value || undefined,
      keyword: keyword.value || undefined
    })
    list.value = r.items
    total.value = r.total
  } catch (e) { err.value = e.message }
  finally { loading.value = false }
}

async function openTask(t) {
  store.setCurrent(t.id)
  router.push(`/tasks/${t.id}`)
}

async function reanalyze(t) {
  try {
    await api.analyze(t.id)
    await load()
  } catch (e) { err.value = e.message }
}

async function removeTask(t) {
  if (!confirm(`确定删除任务「${t.name}」？文件与分析结果都会删除。`)) return
  try {
    await api.deleteTask(t.id)
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

onMounted(() => { load(); loadStorage() })
</script>

<template>
  <div class="page">
    <PageNav
      title="分析任务"
      :sub="`共 ${total} 个任务`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'分析任务'}]">
      <template #actions>
        <input v-model="keyword" class="inp sm" placeholder="搜索文件名" @keyup.enter="page=1; load()" />
        <select v-model="statusFilter" class="inp sm" @change="page=1; load()">
          <option value="">全部状态</option>
          <option value="completed">已完成</option>
          <option value="analyzing">分析中</option>
          <option value="failed">失败</option>
        </select>
        <button class="btn sm" @click="page=1; load()">刷新</button>
      </template>
    </PageNav>

    <div v-if="err" class="err-box">{{ err }}</div>

    <!-- 存储管理 -->
    <div v-if="storage" class="storage-card">
      <div class="sc-left">
        <div class="sc-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          </svg>
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
          清空所有媒体
        </button>
        <button class="btn sm danger" :disabled="purging" @click="purgeAll">
          彻底清理
        </button>
      </div>
      <div v-if="purgeMsg" class="sc-msg">{{ purgeMsg }}</div>
    </div>

    <div class="card">
      <div class="card-body tight">
        <table class="tbl clickable">
          <thead>
            <tr>
              <th>ID</th><th>文件名</th><th>状态</th><th>报文</th>
              <th>大小</th><th>会话</th><th>异常</th><th>创建时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in list" :key="t.id" tabindex="0" @click="openTask(t)" @keydown.enter="openTask(t)">
              <td class="mono">#{{ t.id }}</td>
              <td class="truncate" style="max-width:260px">{{ t.name }}</td>
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
        <div v-if="!list.length && !loading" class="empty">
          还没有分析任务
          <div class="hint">到「分析总览」上传抓包文件开始</div>
        </div>
      </div>
    </div>

    <div class="row mt-16" style="justify-content:flex-end">
      <button class="btn" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span class="mono-sm">{{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
      <button class="btn" :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
    </div>
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
.storage-card {
  display: flex; align-items: center; gap: 16px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 16px;
}
.sc-left { display: flex; align-items: center; gap: 13px; flex: 1; min-width: 260px; }
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

.err-box {
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 12px 14px; font-size: 13px;
  color: var(--critical); margin-bottom: 14px;
}
</style>
