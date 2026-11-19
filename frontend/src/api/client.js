import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 120000
})

client.interceptors.response.use(
  r => r,
  err => {
    const msg = err.response?.data?.error
      || err.response?.data?.detail
      || err.message
      || '请求失败'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)))
  }
)

export const api = {
  health: () => client.get('/health').then(r => r.data),
  rules: () => client.get('/rules').then(r => r.data),

  upload: (file, onProgress) => {
    const fd = new FormData()
    fd.append('file', file)
    return client.post('/tasks/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: e => {
        if (onProgress && e.total) onProgress(Math.round(e.loaded / e.total * 100))
      }
    }).then(r => r.data)
  },

  tasks: (params) => client.get('/tasks', { params }).then(r => r.data),
  task: (id) => client.get(`/tasks/${id}`).then(r => r.data),
  analyze: (id) => client.post(`/tasks/${id}/analyze`).then(r => r.data),
  cancel: (id) => client.post(`/tasks/${id}/cancel`).then(r => r.data),
  deleteTask: (id) => client.delete(`/tasks/${id}`),
  storageUsage: () => client.get('/tasks/storage/usage').then(r => r.data),
  storagePurge: (keep) => client.post('/tasks/storage/purge',
    null, { params: keep != null ? { keep } : {} }).then(r => r.data),
  storagePurgeAll: () => client.delete('/tasks/storage/all').then(r => r.data),
  overview: (id) => client.get(`/tasks/${id}/overview`).then(r => r.data),

  sessions: (taskId, params) => client.get(`/tasks/${taskId}/sessions`, { params }).then(r => r.data),
  session: (id) => client.get(`/sessions/${id}`).then(r => r.data),
  sessionSip: (id) => client.get(`/sessions/${id}/sip`).then(r => r.data),
  sessionTimeline: (id) => client.get(`/sessions/${id}/timeline`).then(r => r.data),
  sessionMedia: (id) => client.get(`/sessions/${id}/media`).then(r => r.data),
  sessionMetrics: (id) => client.get(`/sessions/${id}/metrics`).then(r => r.data),
  sessionDiagnostics: (id) => client.get(`/sessions/${id}/diagnostics`).then(r => r.data),

  diagnostics: (taskId, params) => client.get(`/tasks/${taskId}/diagnostics`, { params }).then(r => r.data),
  ruleStats: (taskId) => client.get(`/tasks/${taskId}/rule-stats`).then(r => r.data),

  // 任务级媒体（无信令的纯码流包也能看到）
  taskMedia: (taskId, params) => client.get(`/tasks/${taskId}/media`, { params }).then(r => r.data),
  taskMetrics: (taskId, ids) => client.get(`/tasks/${taskId}/media-metrics`, {
    params: new URLSearchParams(ids.map(id => ['stream_id', id]))
  }).then(r => r.data),
  taskMediaStats: (taskId) => client.get(`/tasks/${taskId}/media-stats`).then(r => r.data),

  packets: (taskId, params) => client.get(`/tasks/${taskId}/packets`, { params }).then(r => r.data),
  packet: (id) => client.get(`/packets/${id}`).then(r => r.data),

  // DeepSeek
  aiConfig: () => client.get('/ai/config').then(r => r.data),
  aiSaveConfig: (body) => client.post('/ai/config', body).then(r => r.data),
  aiTest: () => client.post('/ai/test').then(r => r.data)
}

export default api
