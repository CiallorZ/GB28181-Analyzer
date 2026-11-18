import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  // 主入口：单上传 + 瀑布式结果
  { path: '/', name: 'workbench', component: () => import('../views/WorkbenchView.vue') },

  // 深入页（从瀑布中的链接进入）
  { path: '/sip', name: 'sip', component: () => import('../views/SipView.vue') },
  { path: '/media', name: 'media', component: () => import('../views/MediaView.vue') },
  { path: '/diagnostics', name: 'diagnostics', component: () => import('../views/DiagnosticsView.vue') },
  { path: '/packets', name: 'packets', component: () => import('../views/PacketsView.vue') },
  { path: '/sessions/:id', name: 'session-detail', component: () => import('../views/SessionDetailView.vue') },
  { path: '/tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') }
]

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    return { top: 0 }
  }
})
