<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { Odometer, Reading, Tickets, Calendar, EditPen, Share, Document, Fold, Expand, User, Monitor } from '@element-plus/icons-vue'
import AppBreadcrumbs from '../components/common/AppBreadcrumbs.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isCollapse = ref(false)
const isMobile = ref(false)
const mobileMenuOpen = ref(false)

const asideWidth = computed(() => {
  if (isMobile.value) return '272px'
  return isCollapse.value ? '64px' : '220px'
})

const activeMenu = computed(() => {
  if (route.path.startsWith('/plans')) return '/plans'
  return route.path
})

const pageTitle = computed(() => (route.meta.title as string) || '课程学习助手')

function handleMenuSelect(index: string) {
  router.push(index)
  if (isMobile.value) mobileMenuOpen.value = false
}

function toggleNavigation() {
  if (isMobile.value) {
    mobileMenuOpen.value = !mobileMenuOpen.value
    return
  }
  isCollapse.value = !isCollapse.value
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
  const nextMobile = window.innerWidth <= 768
  if (isMobile.value !== nextMobile) mobileMenuOpen.value = false
  isMobile.value = nextMobile
}

onMounted(() => {
  handleResize()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

watch(() => route.fullPath, () => {
  if (isMobile.value) mobileMenuOpen.value = false
})
</script>

<template>
  <el-container class="layout-container">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <div
      v-if="isMobile && mobileMenuOpen"
      class="mobile-menu-scrim"
      aria-hidden="true"
      @click="mobileMenuOpen = false"
    />
    <el-aside
      :width="asideWidth"
      class="aside"
      :class="{
        'aside--collapsed': !isMobile && isCollapse,
        'aside--mobile': isMobile,
        'aside--mobile-open': isMobile && mobileMenuOpen,
      }"
      :aria-hidden="isMobile && !mobileMenuOpen"
    >
      <div class="logo">
        <el-icon class="logo-icon" aria-hidden="true"><Reading /></el-icon>
        <span v-if="isMobile || !isCollapse" class="logo-text">课程学习助手</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="!isMobile && isCollapse"
        class="menu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#69a9ff"
        @select="handleMenuSelect"
      >
        <li class="menu-section-label" v-if="isMobile || !isCollapse">学习</li>
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

        <li class="menu-section-label" v-if="isMobile || !isCollapse">学习洞察</li>
        <el-menu-item index="/knowledge-graph">
          <el-icon><Share /></el-icon>
          <span>知识图谱</span>
        </el-menu-item>

        <li class="menu-section-label" v-if="isMobile || !isCollapse">帮助与诊断</li>
        <el-menu-item index="/logs">
          <el-icon><Document /></el-icon>
          <span>日志中心</span>
        </el-menu-item>
        <el-menu-item index="/agent-runs">
          <el-icon><Monitor /></el-icon>
          <span>AI 运行记录</span>
        </el-menu-item>

        <li class="menu-section-label" v-if="isMobile || !isCollapse">设置</li>
        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <span>个人中心</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <button
            type="button"
            class="collapse-btn"
            :aria-label="isMobile ? (mobileMenuOpen ? '关闭主导航' : '打开主导航') : (isCollapse ? '展开主导航' : '收起主导航')"
            :aria-expanded="isMobile ? mobileMenuOpen : !isCollapse"
            @click="toggleNavigation"
          >
            <el-icon>
              <Fold v-if="(!isMobile && !isCollapse) || (isMobile && mobileMenuOpen)" />
              <Expand v-else />
            </el-icon>
          </button>
          <div class="header-title" role="heading" aria-level="1">{{ pageTitle }}</div>
        </div>
        <div class="header-right">
          <el-button text class="username" @click="router.push('/profile')">
            {{ auth.username || '游客' }}
          </el-button>
          <el-button type="danger" plain size="small" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main id="main-content" class="main" tabindex="-1">
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

.skip-link {
  position: fixed;
  left: 16px;
  top: -48px;
  z-index: 3000;
  padding: 10px 14px;
  border-radius: 6px;
  background: #fff;
  color: #1d4ed8;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  transition: top 0.15s ease;
}

.skip-link:focus {
  top: 12px;
}

.aside {
  background-color: #001529;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.2s ease, transform 0.2s ease;
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
  font-size: 24px;
  color: #69a9ff;
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

.aside--mobile .menu:not(.el-menu--collapse) {
  width: 272px;
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
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font-size: 20px;
  cursor: pointer;
  color: #606266;
  margin-right: 8px;
  transition: color 0.2s;
}

.collapse-btn:hover,
.collapse-btn:focus-visible {
  color: #2563eb;
  background: #eff6ff;
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
  color: #475467;
  font-size: 14px;
}

.main {
  background-color: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .aside--mobile {
    position: fixed;
    z-index: 1200;
    height: 100vh;
    left: 0;
    top: 0;
    transform: translateX(-100%);
    box-shadow: 12px 0 30px rgba(0, 0, 0, 0.2);
  }
  .aside--mobile-open {
    transform: translateX(0);
  }
  .mobile-menu-scrim {
    position: fixed;
    inset: 0;
    z-index: 1100;
    background: rgba(15, 23, 42, 0.48);
  }
  .main {
    margin-left: 0;
    padding: 12px;
  }
  .header-title {
    font-size: 16px;
  }
  .header {
    height: 60px;
    padding: 0 12px;
  }
  .header-right {
    gap: 4px;
  }
  .username {
    max-width: 88px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .collapse-btn {
    width: 44px;
    height: 44px;
    margin-left: -8px;
    margin-right: 2px;
  }
}
</style>
