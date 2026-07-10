<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { Odometer, Reading, Tickets, Calendar, EditPen, Share, Document, Fold, Expand } from '@element-plus/icons-vue'
import AppBreadcrumbs from '../components/common/AppBreadcrumbs.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isCollapse = ref(false)

const activeMenu = computed(() => {
  if (route.path.startsWith('/plans')) return '/plans'
  return route.path
})

const pageTitle = computed(() => {
  const path = route.path
  if (path === '/dashboard') return '仪表盘'
  if (path === '/courses') return '课程'
  if (path.startsWith('/courses/') && !path.includes('/materials') && !path.includes('/chat') && !path.includes('/learn') && !path.includes('/outline')) return '课程详情'
  if (path.includes('/materials')) return '课程资料'
  if (path.includes('/chat')) return '课程问答'
  if (path.includes('/learn')) return '文档学习'
  if (path.includes('/outline')) return '知识点大纲'
  if (path === '/todos') return '待办事项'
  if (path.startsWith('/plans')) return '学习计划'
  if (path === '/quizzes') return '测验'
  if (path === '/knowledge-graph') return '知识图谱'
  if (path === '/profile') return '个人中心'
  if (path === '/logs') return '日志中心'
  if (path === '/agent-runs') return 'Agent 审计'
  return '课程学习助手'
})

function handleMenuSelect(index: string) {
  router.push(index)
}

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出确认', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  auth.clearToken()
  router.push('/login')
}

function handleResize() {
  if (window.innerWidth <= 768 && !isCollapse.value) {
    isCollapse.value = true
  }
}

onMounted(() => {
  if (window.innerWidth <= 768) {
    isCollapse.value = true
  }
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <el-container class="layout-container">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="aside" :class="{ 'aside--collapsed': isCollapse }">
      <div class="logo">{{ isCollapse ? '课' : '课程学习助手' }}</div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        class="menu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="handleMenuSelect"
      >
        <el-menu-item index="/dashboard">
          <el-icon><Odometer /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/courses">
          <el-icon><Reading /></el-icon>
          <span>课程</span>
        </el-menu-item>
        <el-menu-item index="/todos">
          <el-icon><Tickets /></el-icon>
          <span>待办</span>
        </el-menu-item>
        <el-menu-item index="/plans">
          <el-icon><Calendar /></el-icon>
          <span>计划</span>
        </el-menu-item>
        <el-menu-item index="/quizzes">
          <el-icon><EditPen /></el-icon>
          <span>测验</span>
        </el-menu-item>
        <!-- Task D: the standalone "Agent 审计" menu entry is removed;
             the /agent-runs route + AgentRunsView are preserved as an
             internal detail-link surface from the log center. -->
        <el-menu-item index="/logs">
          <el-icon><Document /></el-icon>
          <span>日志中心</span>
        </el-menu-item>
        <el-menu-item index="/knowledge-graph">
          <el-icon><Share /></el-icon>
          <span>知识图谱</span>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <span>个人中心</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <div class="header-title">{{ pageTitle }}</div>
        </div>
        <div class="header-right">
          <span class="username">{{ auth.username || '游客' }}</span>
          <el-button type="danger" size="small" @click="handleLogout">登出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <AppBreadcrumbs />
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout-container {
  height: 100vh;
}

.aside {
  background-color: #001529;
  overflow: hidden;
}

.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  background-color: #002140;
  overflow: hidden;
  white-space: nowrap;
}

.menu {
  border-right: none;
}

.menu:not(.el-menu--collapse) {
  width: 220px;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
}

.collapse-btn {
  font-size: 20px;
  cursor: pointer;
  color: #606266;
  margin-right: 12px;
}

.collapse-btn:hover {
  color: #409eff;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.username {
  color: #606266;
  font-size: 14px;
}

.main {
  background-color: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .aside {
    position: fixed;
    z-index: 1001;
    height: 100vh;
    left: 0;
    top: 0;
  }
  .aside--collapsed {
    transform: translateX(-100%);
  }
  .main {
    margin-left: 0;
  }
  .header-title {
    font-size: 16px;
  }
}
</style>
