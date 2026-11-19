import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'

export const useTaskStore = defineStore('task', () => {
  const currentTaskId = ref(Number(localStorage.getItem('currentTaskId')) || null)
  const aiPanelOpen = ref(false)      // AI 设置抽屉（全局）
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
    if (id) localStorage.setItem('currentTaskId', String(id))
    else localStorage.removeItem('currentTaskId')
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

  function openAiPanel() { aiPanelOpen.value = true }
  function closeAiPanel() { aiPanelOpen.value = false }

  return {
    currentTaskId, task, loading, aiPanelOpen,
    isAnalyzing, isReady,
    setCurrent, loadTask, startPolling, stopPolling,
    openAiPanel, closeAiPanel
  }
})
