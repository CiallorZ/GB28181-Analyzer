import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'

function readCurrentTaskId() {
  try {
    const id = Number(localStorage.getItem('currentTaskId'))
    return Number.isSafeInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

function persistCurrentTaskId(id) {
  try {
    if (id) localStorage.setItem('currentTaskId', String(id))
    else localStorage.removeItem('currentTaskId')
  } catch {
    // Storage can be unavailable in restricted browser contexts; memory state still works.
  }
}

export const useTaskStore = defineStore('task', () => {
  const currentTaskId = ref(readCurrentTaskId())
  const aiPanelOpen = ref(false)      // AI 设置抽屉（全局）
  const activeCount = ref(0)
  const task = ref(null)
  const loading = ref(false)
  let pollTimer = null
  let taskRequest = 0

  function setCurrent(id) {
    if (id === currentTaskId.value) return
    taskRequest++
    task.value = null
    loading.value = false
    currentTaskId.value = id
    persistCurrentTaskId(id)
  }

  async function loadTask(id = currentTaskId.value) {
    const request = ++taskRequest
    loading.value = true
    try {
      const data = await api.task(id)
      if (request === taskRequest && id === currentTaskId.value) task.value = data
      return data
    } finally {
      if (request === taskRequest) loading.value = false
    }
  }

  const isAnalyzing = computed(() =>
    task.value && ['pending', 'analyzing'].includes(task.value.status))

  const isReady = computed(() =>
    task.value && task.value.status === 'completed')

  function startPolling(cb) {
    stopPolling()
    pollTimer = setInterval(async () => {
      try {
        const t = await api.task(currentTaskId.value)
        task.value = t
        if (cb) cb(t)
        if (!['pending', 'analyzing'].includes(t.status)) stopPolling()
      } catch { /* 忽略轮询错误 */ }
    }, 1200)
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  }

  let activeRefresh = null
  let activeRefreshGeneration = 0
  let activeRefreshQueued = false
  async function refreshActive() {
    // Calls from navigation and analysis actions may arrive during the global poll.
    // Coalesce them into one trailing request and never apply an obsolete response.
    activeRefreshGeneration++
    activeRefreshQueued = true
    if (activeRefresh) return activeRefresh
    activeRefresh = (async () => {
      while (activeRefreshQueued) {
        activeRefreshQueued = false
        const request = activeRefreshGeneration
        try {
          const count = Number((await api.activeTasks()).count) || 0
          if (request === activeRefreshGeneration) activeCount.value = count
        } catch {
          // The last known count is safer than assuming no work is running.
        }
      }
    })().finally(() => {
      activeRefresh = null
      // A caller may arrive after the loop settles but before this finally runs.
      if (activeRefreshQueued) return refreshActive()
    })
    return activeRefresh
  }

  const aiFocus = ref('general')
  function openAiPanel(focus = 'general') {
    aiFocus.value = focus
    aiPanelOpen.value = true
  }
  function closeAiPanel() { aiPanelOpen.value = false }

  return {
    currentTaskId, task, loading, aiPanelOpen, aiFocus, activeCount,
    isAnalyzing, isReady,
    setCurrent, loadTask, startPolling, stopPolling, refreshActive,
    openAiPanel, closeAiPanel
  }
})
