import { createRouter, createWebHistory } from 'vue-router'
import { resolveTaskContext } from './taskNavigation'
import { useTaskStore } from '../stores/task'
// 工作台是落地页，每次都会加载：静态引入让构建期就能算准首屏预算，
// 其余页面仍按路由懒加载。
import WorkbenchView from '../views/WorkbenchView.vue'

const routes = [
  // 主入口：单上传 + 瀑布式结果
  { path: '/', name: 'workbench', component: WorkbenchView },

  // 深入页（从瀑布中的链接进入）
  { path: '/sip', name: 'sip', component: () => import('../views/SipView.vue') },
  { path: '/media', name: 'media', component: () => import('../views/MediaView.vue') },
  { path: '/diagnostics', name: 'diagnostics', component: () => import('../views/DiagnosticsView.vue') },
  { path: '/packets', name: 'packets', component: () => import('../views/PacketsView.vue') },
  { path: '/sessions/:id', name: 'session-detail', component: () => import('../views/SessionDetailView.vue') },
  // 历史任务深链接：/tasks/:id 打开对应任务的分析结果（由全局守卫设置当前任务）
  { path: '/tasks/:id(\\d+)', name: 'task', component: WorkbenchView },
  { path: '/tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
  { path: '/compare', component: () => import('../views/CompareView.vue') },
  { path: '/compare/:id(\\d+)', component: () => import('../views/ComparisonDetail.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },

  // 未知路径回到工作台，避免白屏
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    return { top: 0 }
  }
})

router.beforeEach(to => resolveTaskContext(to, useTaskStore()))

export default router
