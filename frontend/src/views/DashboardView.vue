<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  Calendar,
  ChatDotRound,
  CircleCheck,
  Collection,
  Document,
  EditPen,
  Monitor,
  Reading,
  Tickets,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { getDashboardSummary, type DashboardSummary } from '../api/dashboard'
import { listCourses, type Course } from '../api/course'
import { listTodos, updateTodo, type Todo } from '../api/plan'
import { getAgentRuns, type AgentRun } from '../api/audit'
import { getActiveConfig } from '../api/llmConfig'
import { parseApiError } from '../utils/error'
import { MAX_PAGE_SIZE } from '../constants/pagination'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const summary = ref<DashboardSummary | null>(null)
const todayTodos = ref<Todo[]>([])
const recentCourses = ref<Course[]>([])
const recentRuns = ref<AgentRun[]>([])
// null = unknown / still checking, true = a real LLM is configured, false = Mock mode
const llmConfigured = ref<boolean | null>(null)

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const todayString = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
})

const weekDay = computed(() => {
  const days = ['日', '一', '二', '三', '四', '五', '六']
  return `星期${days[new Date().getDay()]}`
})

const stats = computed(() => {
  const s = summary.value
  return [
    { key: 'course', label: '课程数', value: s?.course_count ?? 0, icon: Reading, color: '#409EFF', route: '/courses' },
    { key: 'material', label: '资料数', value: s?.material_count ?? 0, icon: Document, color: '#67C23A', route: '/courses' },
    { key: 'knowledge', label: '知识点数', value: s?.knowledge_point_count ?? 0, icon: Collection, color: '#E6A23C', route: '/knowledge-graph' },
    { key: 'todo', label: '今日待办', value: s?.todo_today_count ?? 0, icon: Calendar, color: '#F56C6C', route: '/todos' },
    { key: 'completed', label: '已完成待办', value: s?.todo_completed_count ?? 0, icon: CircleCheck, color: '#909399', route: '/todos' },
    { key: 'agent', label: 'AI 助手记录', value: s?.agent_run_count ?? 0, icon: Monitor, color: '#9C27B0', route: '/agent-runs' },
  ]
})

const statusTagType: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
  succeeded: 'success',
  success: 'success',
  failed: 'danger',
  running: 'warning',
  started: 'warning',
}
const statusLabel: Record<string, string> = {
  succeeded: '成功',
  success: '成功',
  failed: '失败',
  running: '进行中',
  started: '进行中',
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatDateTime(dt: string | null | undefined): string {
  if (!dt) return '-'
  const d = new Date(dt)
  if (isNaN(d.getTime())) return dt
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(
    d.getMinutes(),
  ).padStart(2, '0')}`
}

async function fetchAll() {
  loading.value = true
  try {
    const [sumResp, todosResp, coursesResp, runsResp] = await Promise.all([
      getDashboardSummary(),
      listTodos({ date: todayString.value }),
      listCourses({ page: 1, page_size: MAX_PAGE_SIZE }),
      getAgentRuns({ limit: 5, offset: 0 }),
    ])
    summary.value = sumResp.data
    todayTodos.value = todosResp.data.items.slice(0, 5)
    recentCourses.value = coursesResp.data.items.slice(0, 4)
    recentRuns.value = runsResp.data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取仪表盘数据失败'))
  } finally {
    loading.value = false
  }
}

function go(path: string) {
  router.push(path)
}
function goCourseChat(id: number) {
  router.push(`/courses/${id}/chat`)
}
function goCourseMaterials(id: number) {
  router.push(`/courses/${id}/materials`)
}

function goQuickUpload() {
  if (recentCourses.value.length > 0) {
    router.push(`/courses/${recentCourses.value[0].id}/materials`)
  } else {
    router.push('/courses')
  }
}
function goQuickChat() {
  if (recentCourses.value.length > 0) {
    router.push(`/courses/${recentCourses.value[0].id}/chat`)
  } else {
    router.push('/courses')
  }
}

async function handleCompleteTodo(todo: Todo) {
  try {
    const { data } = await updateTodo(todo.id, { status: 'completed' })
    const idx = todayTodos.value.findIndex(t => t.id === todo.id)
    if (idx >= 0) todayTodos.value[idx] = data
    ElMessage.success('已完成')
  } catch (err) {
    ElMessage.error(parseApiError(err, '完成待办失败'))
  }
}

function handleRefresh() {
  fetchAll()
  checkLlmConfig()
}

async function checkLlmConfig() {
  try {
    const { data } = await getActiveConfig()
    llmConfigured.value = data.config !== null
  } catch {
    // If the request itself fails we cannot reliably tell whether the user is in
    // Mock mode, so avoid showing a potentially misleading banner.
    llmConfigured.value = null
  }
}

onMounted(() => {
  fetchAll()
  checkLlmConfig()
})
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- Mock 模式提示 -->
    <el-alert
      v-if="llmConfigured === false"
      class="mock-banner"
      type="warning"
      show-icon
      :closable="false"
    >
      <template #title>
        当前处于 Mock 模式 — 尚未配置真实的大语言模型，AI 助手功能将返回模拟数据。
      </template>
      <template #default>
        <el-link type="primary" underline="never" @click="go('/profile')">
          前往个人中心配置 LLM →
        </el-link>
      </template>
    </el-alert>

    <!-- 欢迎区 -->
    <el-card class="welcome-card" shadow="never">
      <div class="welcome">
        <div class="welcome-info">
          <div class="welcome-title">{{ greeting }}，{{ auth.username || '同学' }}</div>
          <div class="welcome-sub">
            今天是 {{ todayString }} {{ weekDay }}，坚持每日学习，稳步提升。
          </div>
        </div>
        <div class="welcome-actions">
          <el-button :icon="ArrowRight" @click="go('/todos')">查看全部待办</el-button>
          <el-button type="primary" @click="handleRefresh">刷新</el-button>
        </div>
      </div>
    </el-card>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col v-for="s in stats" :key="s.key" :xs="12" :sm="8" :md="4">
        <el-card class="stat-card" shadow="hover" @click="go(s.route)">
          <div class="stat-body">
            <el-icon class="stat-icon" :style="{ color: s.color }">
              <component :is="s.icon" />
            </el-icon>
            <div class="stat-text">
              <div class="stat-value">{{ s.value }}</div>
              <div class="stat-label">{{ s.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷入口 -->
    <el-card class="section-card" shadow="never">
      <div class="section-title">快捷入口</div>
      <div class="quick-actions">
        <div class="action-card" @click="goQuickUpload">
          <div class="action-icon-wrap" style="background: rgba(64, 158, 255, 0.12); color: #409EFF;">
            <el-icon><Tickets /></el-icon>
          </div>
          <div class="action-text">
            <span class="action-label">上传资料</span>
            <span class="action-desc">添加课程学习材料</span>
          </div>
        </div>
        <div class="action-card" @click="goQuickChat">
          <div class="action-icon-wrap" style="background: rgba(103, 194, 58, 0.12); color: #67C23A;">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="action-text">
            <span class="action-label">课程问答</span>
            <span class="action-desc">与 AI 助手对话</span>
          </div>
        </div>
        <div class="action-card" @click="go('/plans')">
          <div class="action-icon-wrap" style="background: rgba(230, 162, 60, 0.12); color: #E6A23C;">
            <el-icon><Calendar /></el-icon>
          </div>
          <div class="action-text">
            <span class="action-label">生成计划</span>
            <span class="action-desc">创建学习计划</span>
          </div>
        </div>
        <div class="action-card" @click="go('/quizzes')">
          <div class="action-icon-wrap" style="background: rgba(245, 108, 108, 0.12); color: #F56C6C;">
            <el-icon><EditPen /></el-icon>
          </div>
          <div class="action-text">
            <span class="action-label">生成测验</span>
            <span class="action-desc">检验学习成果</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16">
      <!-- 今日待办 -->
      <el-col :xs="24" :md="12">
        <el-card class="section-card" shadow="never">
          <div class="section-head">
            <span class="section-title">今日待办</span>
            <el-button link type="primary" @click="go('/todos')">更多</el-button>
          </div>
          <el-empty
            v-if="todayTodos.length === 0"
            :image-size="80"
          >
            <template #description>
              <span>今日暂无待办，</span>
              <el-link type="primary" underline="never" @click="go('/plans')">
                去计划页面创建学习计划吧
              </el-link>
            </template>
          </el-empty>
          <ul v-else class="todo-list">
            <li v-for="t in todayTodos" :key="t.id" class="todo-item">
              <span class="todo-title">{{ t.title }}</span>
              <div class="todo-actions">
                <el-tag size="small" :type="t.status === 'completed' ? 'success' : 'warning'">
                  {{ t.status === 'completed' ? '已完成' : '待完成' }}
                </el-tag>
                <el-button
                  v-if="t.status !== 'completed'"
                  link
                  type="primary"
                  size="small"
                  @click="handleCompleteTodo(t)"
                >
                  完成
                </el-button>
              </div>
            </li>
          </ul>
        </el-card>
      </el-col>

      <!-- 最近课程 -->
      <el-col :xs="24" :md="12">
        <el-card class="section-card" shadow="never">
          <div class="section-head">
            <span class="section-title">最近课程</span>
            <el-button link type="primary" @click="go('/courses')">更多</el-button>
          </div>
          <el-empty
            v-if="recentCourses.length === 0"
            :image-size="80"
          >
            <template #description>
              <span>暂无课程，</span>
              <el-link type="primary" underline="never" @click="go('/courses')">
                去添加你的第一门课程吧
              </el-link>
            </template>
          </el-empty>
          <ul v-else class="course-list">
            <li v-for="c in recentCourses" :key="c.id" class="course-item">
              <div class="course-info">
                <span
                  class="course-dot"
                  :style="{ background: c.color || '#409EFF' }"
                ></span>
                <div>
                  <div class="course-name">{{ c.name }}</div>
                  <div class="course-meta">
                    {{ c.teacher || '未设置' }} · {{ c.semester || '-' }}
                  </div>
                </div>
              </div>
              <div class="course-actions">
                <el-button link size="small" @click="goCourseMaterials(c.id)">
                  资料
                </el-button>
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="goCourseChat(c.id)"
                >
                  问答
                </el-button>
              </div>
            </li>
          </ul>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近 AI 助手活动 -->
    <el-card class="section-card" shadow="never">
      <div class="section-head">
        <span class="section-title">最近 AI 助手活动</span>
        <el-button link type="primary" @click="go('/agent-runs')">更多</el-button>
      </div>
      <el-empty
        v-if="recentRuns.length === 0"
        :image-size="80"
      >
        <template #description>
          <span>暂无 AI 助手活动记录，</span>
          <el-link type="primary" underline="never" @click="goQuickChat">
            去与课程 AI 助手对话试试吧
          </el-link>
        </template>
      </el-empty>
      <el-table v-else :data="recentRuns" stripe size="small">
        <el-table-column prop="run_type" label="类型" width="120" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status] || 'info'" size="small">
              {{ statusLabel[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100" align="center">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column
          prop="model_name"
          label="模型"
          min-width="120"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ row.model_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="140">
          <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.welcome-card :deep(.el-card__body) {
  padding: 20px 24px;
}

.welcome {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.welcome-title {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.welcome-sub {
  margin-top: 6px;
  color: #606266;
  font-size: 14px;
}

.welcome-actions {
  display: flex;
  gap: 8px;
}

.stat-row {
  margin-bottom: 0;
}

.stat-card :deep(.el-card__body) {
  padding: 16px;
}

.stat-card {
  cursor: pointer;
  transition: transform 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
}

.stat-body {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat-icon {
  font-size: 28px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 2px;
}

.section-card :deep(.el-card__body) {
  padding: 16px 20px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.mock-banner {
  margin-bottom: 0;
}

.mock-banner :deep(.el-alert__description) {
  margin-top: 6px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-card:hover {
  border-color: #c6e2ff;
  background: #f5f9ff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.12);
}

.action-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 10px;
  flex-shrink: 0;
}

.action-icon-wrap .el-icon {
  font-size: 22px;
}

.action-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.action-label {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.action-desc {
  font-size: 12px;
  color: #909399;
}

.todo-list,
.course-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.todo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.todo-item:last-child {
  border-bottom: none;
}

.todo-title {
  font-size: 14px;
  color: #303133;
}

.todo-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.course-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}

.course-item:last-child {
  border-bottom: none;
}

.course-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.course-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.course-name {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}

.course-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.course-actions {
  display: flex;
  gap: 4px;
}
</style>
