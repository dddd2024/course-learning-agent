import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { requiresAuth: false, title: '登录' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('../views/DashboardView.vue'),
        meta: { requiresAuth: true, title: '仪表盘' },
      },
      {
        path: 'courses',
        name: 'courses',
        component: () => import('../views/CoursesView.vue'),
        meta: { requiresAuth: true, title: '课程' },
      },
      {
        path: 'courses/:id',
        name: 'course-detail',
        component: () => import('../views/CourseDetailView.vue'),
        meta: { requiresAuth: true, title: '课程详情' },
      },
      {
        path: 'courses/:id/materials',
        name: 'course-materials',
        component: () => import('../views/MaterialsView.vue'),
        meta: { requiresAuth: true, title: '课程资料' },
      },
      {
        path: 'courses/:id/chat',
        name: 'course-chat',
        component: () => import('../views/ChatView.vue'),
        meta: { requiresAuth: true, title: '课程问答' },
      },
      {
        path: 'courses/:id/learn',
        name: 'course-learn',
        component: () => import('../views/LearnView.vue'),
        meta: { requiresAuth: true, title: '文档学习' },
      },
      {
        path: 'courses/:id/outline',
        name: 'course-outline',
        component: () => import('../views/OutlineView.vue'),
        meta: { requiresAuth: true, title: '知识点大纲' },
      },
      {
        path: 'plans',
        name: 'plans',
        component: () => import('../views/PlansView.vue'),
        meta: { requiresAuth: true, title: '学习计划' },
      },
      {
        path: 'plans/multi',
        name: 'plans-multi',
        component: () => import('../views/MultiPlanView.vue'),
        meta: { requiresAuth: true, title: '跨课程计划' },
      },
      {
        path: 'quizzes',
        name: 'quizzes',
        component: () => import('../views/QuizView.vue'),
        meta: { requiresAuth: true, title: '测验' },
      },
      {
        path: 'todos',
        name: 'todos',
        component: () => import('../views/TodosView.vue'),
        meta: { requiresAuth: true, title: '待办事项' },
      },
      {
        path: 'agent-runs',
        name: 'agent-runs',
        component: () => import('../views/AgentRunsView.vue'),
        meta: { requiresAuth: true, title: 'Agent 审计' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('../views/LogsView.vue'),
        meta: { requiresAuth: true, title: '日志中心' },
      },
      {
        path: 'knowledge-graph',
        name: 'knowledge-graph',
        component: () => import('../views/KnowledgeGraphView.vue'),
        meta: { requiresAuth: true, title: '知识图谱' },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('../views/ProfileView.vue'),
        meta: { requiresAuth: true, title: '个人中心' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  // Redo Task A: the guard must await /auth/me validation before trusting
  // the token. A stale localStorage token that the backend rejects (401)
  // is cleared by ensureAuthReady and the user is sent to /login.
  const auth = useAuthStore()
  const ok = await auth.ensureAuthReady()
  if (to.meta.requiresAuth) {
    if (!ok) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  if (to.meta.requiresAuth === false && ok) {
    // Already authenticated — skip the login/register page.
    if (to.path === '/login') return '/dashboard'
  }
})

export default router
