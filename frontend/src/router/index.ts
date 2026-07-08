import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { requiresAuth: false },
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
        meta: { requiresAuth: true },
      },
      {
        path: 'courses',
        name: 'courses',
        component: () => import('../views/CoursesView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'courses/:id',
        name: 'course-detail',
        component: () => import('../views/CourseDetailView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'courses/:id/materials',
        name: 'course-materials',
        component: () => import('../views/MaterialsView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'courses/:id/chat',
        name: 'course-chat',
        component: () => import('../views/ChatView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'courses/:id/outline',
        name: 'course-outline',
        component: () => import('../views/OutlineView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'plans',
        name: 'plans',
        component: () => import('../views/PlansView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'plans/multi',
        name: 'plans-multi',
        component: () => import('../views/MultiPlanView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'quizzes',
        name: 'quizzes',
        component: () => import('../views/QuizView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'todos',
        name: 'todos',
        component: () => import('../views/TodosView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'agent-runs',
        name: 'agent-runs',
        component: () => import('../views/AgentRunsView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('../views/LogsView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'knowledge-graph',
        name: 'knowledge-graph',
        component: () => import('../views/KnowledgeGraphView.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('../views/ProfileView.vue'),
        meta: { requiresAuth: true },
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

router.beforeEach((to) => {
  // Task B: read token from the auth store (sessionStorage by default,
  // localStorage only when "记住登录" was chosen) instead of reading
  // localStorage directly. A stale localStorage token must NOT bypass
  // the login page.
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) {
    auth.clearToken()
    return '/login'
  }
  if (to.meta.requiresAuth === false && auth.token) {
    // Already logged in — skip the login page.
    return '/dashboard'
  }
})

export default router
