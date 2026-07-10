<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { Odometer, Reading, Tickets, Calendar, EditPen, Share, Document, Fold, Expand, User } from '@element-plus/icons-vue'
import AppBreadcrumbs from '../components/common/AppBreadcrumbs.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isCollapse = ref(false)

const activeMenu = computed(() => {
  if (route.path.startsWith('/plans')) return '/plans'
  return route.path
})

const pageTitle = computed(() => (route.meta.title as string) || '课程学习助手')

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
      <div class="logo">
        <span class="logo-icon">📚</span>
        <span v-if="!isCollapse" class="logo-text">课程学习助手</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        class="menu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="handleMenuSelect"
      >
        <li class="menu-section-label" v-if="!isCollapse">学习</li>
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

        <li class="menu-section-label" v-if="!isCollapse">工具</li>
        <el-menu-item index="/knowledge-graph">
          <el-icon><Share /></el-icon>
          <span>知识图谱</span>
        </el-menu-item>
        <el-menu-item index="/logs">
          <el-icon><Document /></el-icon>
          <span>日志中心</span>
        </el-menu-item>

        <li class="menu-section-label" v-if="!isCollapse">设置</li>
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
  overflow-y: auto;
  overflow-x: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  background-color: #002140;
  overflow: hidden;
  white-space: nowrap;
}

.logo-icon {
  font-size: 22px;
}

.logo-text {
  font-size: 15px;
}

.menu {
  border-right: none;
}

.menu:not(.el-menu--collapse) {
  width: 220px;
}

.menu-section-label {
  padding: 16px 20px 4px;
  font-size: 11px;
  font-weight: 600;
  color: #5b6b7e;
  text-transform: uppercase;
  letter-spacing: 1px;
  list-style: none;
  user-select: none;
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
  transition: color 0.2s;
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
