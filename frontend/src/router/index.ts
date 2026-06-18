import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/chat',
      },
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('@/views/chat/ChatView.vue'),
      },
      {
        path: 'notebook',
        name: 'Notebook',
        component: () => import('@/views/notebook/NotebookView.vue'),
      },
      {
        path: 'explore',
        name: 'Explore',
        component: () => import('@/views/explore/ExploreView.vue'),
      },
      {
        path: 'datasource',
        name: 'DataSource',
        component: () => import('@/views/datasource/DataSourceView.vue'),
      },
      {
        path: 'skill',
        name: 'Skill',
        component: () => import('@/views/skill/SkillView.vue'),
      },
      {
        path: 'operator',
        name: 'Operator',
        component: () => import('@/views/operator/OperatorView.vue'),
      },
      {
        path: 'pipeline',
        name: 'Pipeline',
        component: () => import('@/views/pipeline/PipelineView.vue'),
      },
      {
        path: 'workflow',
        redirect: '/pipeline',
      },
      {
        path: 'schedule',
        name: 'Schedule',
        component: () => import('@/views/schedule/ScheduleView.vue'),
      },
      {
        path: 'filelink',
        name: 'FileLink',
        component: () => import('@/views/filelink/FileLinkView.vue'),
      },
      {
        path: 'config',
        name: 'Config',
        component: () => import('@/views/config/ConfigView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth !== false && !token) {
    next({ name: 'Login' })
  } else {
    next()
  }
})

export default router
