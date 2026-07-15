<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { Odometer, Reading, Tickets, Calendar, EditPen, Share, Document, Fold, Expand, User, Monitor, ArrowDown, SwitchButton } from '@element-plus/icons-vue'
import AppBreadcrumbs from '../components/common/AppBreadcrumbs.vue'
import InkAmbient from '../components/common/InkAmbient.vue'

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

function handleUserCommand(command: string) {
  if (command === 'profile') router.push('/profile')
  if (command === 'logout') handleLogout()
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
          <span class="online-mark"><i /> 学习空间在线</span>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <button type="button" class="user-menu" aria-label="打开用户菜单">
              <span class="user-avatar">{{ (auth.username || '游').slice(0, 1).toUpperCase() }}</span>
              <span class="username">{{ auth.username || '游客' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile"><el-icon><User /></el-icon>个人中心</el-dropdown-item>
                <el-dropdown-item command="logout" divided><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main id="main-content" class="main" tabindex="-1">
        <InkAmbient />
        <AppBreadcrumbs />
        <router-view v-slot="{ Component }">
          <transition name="ink-page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout-container {
  height: 100dvh;
  background: var(--ink-night);
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
  background-color: var(--ink-night);
  background-image: url('../assets/ink-night-texture.webp');
  background-size: cover;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.28s var(--ease-ink), transform 0.28s var(--ease-ink);
  border-right: 1px solid rgba(225, 229, 218, 0.12);
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--paper);
  font-size: 16px;
  font-weight: 600;
  background: rgba(8, 23, 30, 0.56);
  border-bottom: 1px solid rgba(225, 229, 218, 0.12);
  overflow: hidden;
  white-space: nowrap;
}

.logo-icon {
  font-size: 24px;
  color: var(--celadon);
}

.logo-text {
  font-size: 15px;
}

.menu {
  border-right: none;
  background: transparent;
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
  color: rgba(225, 229, 218, 0.43);
  text-transform: uppercase;
  letter-spacing: 1px;
  list-style: none;
  user-select: none;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  background: rgba(245, 240, 228, 0.86);
  border-bottom: 1px solid rgba(42, 54, 56, 0.13);
  backdrop-filter: blur(14px);
  box-shadow: none;
  padding: 0 22px;
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
  color: var(--ink-muted);
  margin-right: 8px;
  transition: color 0.2s;
}

.collapse-btn:hover,
.collapse-btn:focus-visible {
  color: var(--indigo-ink);
  background: rgba(44, 71, 86, 0.08);
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.08em;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.online-mark {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--ink-muted);
  font-size: 12px;
}

.online-mark i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--celadon-strong);
  box-shadow: 0 0 0 4px rgba(103, 143, 129, 0.12);
}

.user-menu {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 4px 8px;
  border: 0;
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}

.user-avatar {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: var(--paper);
  background: var(--indigo-ink);
  font-family: var(--font-display);
}

.username {
  color: var(--ink);
  font-size: 14px;
}

.main {
  position: relative;
  background-color: var(--paper);
  background-image: url('../assets/ink-paper-mountains.webp');
  background-size: cover;
  background-position: center top;
  padding: 0 24px 28px;
  overflow-y: auto;
}

.main > *:not(.ink-ambient) {
  position: relative;
  z-index: 1;
}

:deep(.el-menu-item) {
  margin: 4px 10px;
  border-radius: 4px;
  color: rgba(236, 235, 225, 0.72);
}

:deep(.el-menu-item:hover) {
  color: var(--paper);
  background: rgba(228, 224, 207, 0.08);
}

:deep(.el-menu-item.is-active) {
  color: var(--paper);
  background: rgba(222, 216, 197, 0.14);
  box-shadow: inset 3px 0 0 var(--celadon);
}

.ink-page-enter-active,
.ink-page-leave-active {
  transition: opacity 0.24s ease, transform 0.3s var(--ease-ink), filter 0.3s ease;
}

.ink-page-enter-from {
  opacity: 0;
  transform: translateY(8px);
  filter: blur(3px);
}

.ink-page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
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
    padding: 0 12px 20px;
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
  .online-mark,
  .username {
    display: none;
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
