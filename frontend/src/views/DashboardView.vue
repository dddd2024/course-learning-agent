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
const quickCourseDialogVisible = ref(false)
const quickCourseAction = ref<'materials' | 'chat'>('materials')

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

const primaryCourse = computed(() => recentCourses.value[0] ?? null)
const nextTodo = computed(() => todayTodos.value.find(todo => todo.status !== 'completed') ?? null)
const completedTodos = computed(() => todayTodos.value.filter(todo => todo.status === 'completed').length)
const todayProgress = computed(() => {
  if (todayTodos.value.length === 0) return 0
  return Math.round((completedTodos.value / todayTodos.value.length) * 100)
})
const currentCourseName = computed(() => nextTodo.value?.course_name || primaryCourse.value?.name || '创建第一门课程')
const currentTeacher = computed(() => primaryCourse.value?.teacher || '课程学习助手')
const currentSemester = computed(() => primaryCourse.value?.semester || '自主学习空间')
const nextTaskTitle = computed(() => nextTodo.value?.title || '整理课程资料并建立学习路径')
const nextTaskMinutes = computed(() => nextTodo.value?.estimate_minutes || 30)

function handleContinue() {
  const courseId = nextTodo.value?.course_id || primaryCourse.value?.id
  if (courseId) router.push(`/courses/${courseId}`)
  else router.push('/courses')
}

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
  const results = await Promise.allSettled([
      getDashboardSummary(),
      listTodos({ date: todayString.value }),
      listCourses({ page: 1, page_size: MAX_PAGE_SIZE }),
      getAgentRuns({ limit: 5, offset: 0 }),
  ])

  if (results[0].status === 'fulfilled') summary.value = results[0].value.data
  if (results[1].status === 'fulfilled') todayTodos.value = results[1].value.data.items.slice(0, 5)
  if (results[2].status === 'fulfilled') recentCourses.value = results[2].value.data.items.slice(0, 4)
  if (results[3].status === 'fulfilled') recentRuns.value = results[3].value.data.items

  const failedCount = results.filter((result) => result.status === 'rejected').length
  if (failedCount > 0) {
    const firstFailure = results.find((result) => result.status === 'rejected')
    const reason = firstFailure?.status === 'rejected'
      ? parseApiError(firstFailure.reason, '部分数据暂时不可用')
      : '部分数据暂时不可用'
    ElMessage.warning(`${reason}（${failedCount} 个区块），其他内容已正常显示`)
  }
  loading.value = false
}

function go(path: string) {
  router.push(path)
}
function goQuickUpload() {
  openQuickCourse('materials')
}
function goQuickChat() {
  openQuickCourse('chat')
}

function openQuickCourse(action: 'materials' | 'chat') {
  if (recentCourses.value.length === 0) {
    router.push('/courses')
    return
  }
  if (recentCourses.value.length === 1) {
    chooseQuickCourse(recentCourses.value[0], action)
    return
  }
  quickCourseAction.value = action
  quickCourseDialogVisible.value = true
}

function chooseQuickCourse(course: Course, action = quickCourseAction.value) {
  quickCourseDialogVisible.value = false
  router.push(`/courses/${course.id}/${action}`)
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
    <div class="dashboard-grid">
      <main class="learning-stage">
        <section class="welcome">
          <div>
            <p class="eyebrow">{{ todayString }} · {{ weekDay }}</p>
            <h1>{{ greeting }}，{{ auth.username || '同学' }}</h1>
            <p>专注今日，稳步前进。让每一次学习都有清晰的依据与方向。</p>
          </div>
          <el-button text class="refresh-button" @click="handleRefresh">同步学习状态</el-button>
        </section>

        <section class="current-learning" aria-labelledby="current-course-heading">
          <p class="section-kicker">当前学习</p>
          <div class="course-focus">
            <div class="course-seal" aria-hidden="true">
              <el-icon><Reading /></el-icon>
              <span>{{ currentCourseName.slice(0, 4) }}</span>
            </div>
            <div class="course-copy">
              <h2 id="current-course-heading">{{ currentCourseName }}</h2>
              <p>{{ currentTeacher }} · {{ currentSemester }}</p>
              <div class="progress-line">
                <span>今日进度</span>
                <strong>{{ todayProgress }}%</strong>
                <el-progress :percentage="todayProgress" :show-text="false" />
              </div>
              <div class="course-facts">
                <span>课程 {{ summary?.course_count ?? 0 }} 门</span>
                <span>资料 {{ summary?.material_count ?? 0 }} 份</span>
                <span>知识点 {{ summary?.knowledge_point_count ?? 0 }} 个</span>
              </div>
            </div>
          </div>
        </section>

        <section class="next-action" aria-labelledby="next-task-heading">
          <div class="next-action-icon"><el-icon><Tickets /></el-icon></div>
          <div class="next-action-copy">
            <p class="section-kicker">下一步行动 · 预计 {{ nextTaskMinutes }} 分钟</p>
            <h2 id="next-task-heading">{{ nextTaskTitle }}</h2>
            <p>{{ nextTodo ? '根据今日学习计划继续推进，完成后可直接标记状态。' : '从课程空间开始整理资料，AI 将为你生成下一步学习建议。' }}</p>
          </div>
          <el-button type="primary" size="large" @click="handleContinue">
            继续学习 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </section>

        <section class="ai-guidance">
          <div class="guidance-mark"><el-icon><Collection /></el-icon></div>
          <div>
            <p class="section-kicker">AI 学习建议</p>
            <h3>先完成当前任务，再用一次课程问答巩固关键概念。</h3>
            <p>回答会关联课程资料与知识点证据，帮助你把“看过”变成“掌握”。</p>
            <button v-if="llmConfigured === false" class="mode-note" type="button" @click="go('/profile')">
              当前为 Mock 演示模式 · 配置真实模型
            </button>
          </div>
          <el-button plain @click="goQuickChat">开始提问</el-button>
        </section>

        <section class="tool-strip" aria-label="学习工具">
          <button type="button" @click="goQuickUpload"><el-icon><Tickets /></el-icon><span>上传资料</span></button>
          <button type="button" @click="goQuickChat"><el-icon><ChatDotRound /></el-icon><span>课程问答</span></button>
          <button type="button" @click="go('/plans')"><el-icon><Calendar /></el-icon><span>生成计划</span></button>
          <button type="button" @click="go('/quizzes')"><el-icon><EditPen /></el-icon><span>生成测验</span></button>
        </section>
      </main>

      <aside class="learning-rail">
        <section class="rail-section plan-section">
          <div class="rail-heading">
            <h2><el-icon><Calendar /></el-icon> 今日学习计划</h2>
            <el-button link @click="go('/todos')">完整计划</el-button>
          </div>
          <div v-if="todayTodos.length" class="timeline">
            <article v-for="todo in todayTodos.slice(0, 4)" :key="todo.id" :class="['timeline-item', `is-${todo.status}`]">
              <span class="timeline-dot"><el-icon v-if="todo.status === 'completed'"><CircleCheck /></el-icon></span>
              <div>
                <p>{{ todo.estimate_minutes }} 分钟 · {{ todo.course_name || '自主学习' }}</p>
                <h3>{{ todo.title }}</h3>
                <button v-if="todo.status !== 'completed'" type="button" @click="handleCompleteTodo(todo)">标记完成</button>
                <small v-else>已完成</small>
              </div>
            </article>
          </div>
          <div v-else class="rail-empty">
            <p>今天还没有计划</p>
            <el-button link @click="go('/plans')">生成学习计划</el-button>
          </div>
        </section>

        <section class="rail-section insight-section">
          <div class="rail-heading">
            <h2>学习洞察</h2>
            <el-button link @click="go('/knowledge-graph')">查看图谱</el-button>
          </div>
          <div class="insight-grid">
            <div><strong>{{ summary?.knowledge_point_count ?? 0 }}</strong><span>知识点</span></div>
            <div><strong>{{ completedTodos }}</strong><span>今日完成</span></div>
            <div><strong>{{ summary?.agent_run_count ?? 0 }}</strong><span>AI 运行</span></div>
          </div>
          <div class="mastery-progress" aria-label="今日计划完成度">
            <div><span>今日计划完成度</span><strong>{{ todayProgress }}%</strong></div>
            <el-progress :percentage="todayProgress" :show-text="false" :stroke-width="5" />
          </div>
          <p class="insight-note">知识关联正在逐步形成，建议优先补齐掌握度较低的节点。</p>
        </section>

        <section class="rail-section run-section">
          <div class="rail-heading">
            <h2><el-icon><Monitor /></el-icon> AI 最近运行</h2>
            <el-button link @click="go('/agent-runs')">全部</el-button>
          </div>
          <div v-if="recentRuns.length" class="run-list">
            <article v-for="run in recentRuns.slice(0, 3)" :key="run.id">
              <span :class="['run-status', `is-${run.status}`]" />
              <div><strong>{{ run.run_type }}</strong><small>{{ formatDateTime(run.started_at) }} · {{ formatDuration(run.duration_ms) }}</small></div>
              <el-tag :type="statusTagType[run.status] || 'info'" size="small">{{ statusLabel[run.status] || run.status }}</el-tag>
            </article>
          </div>
          <p v-else class="rail-empty">还没有 AI 运行记录</p>
        </section>
      </aside>
    </div>

    <el-dialog
      v-model="quickCourseDialogVisible"
      :title="quickCourseAction === 'materials' ? '选择要上传资料的课程' : '选择要提问的课程'"
      width="460px"
    >
      <div class="quick-course-list">
        <button
          v-for="course in recentCourses"
          :key="course.id"
          type="button"
          class="quick-course-option"
          @click="chooseQuickCourse(course)"
        >
          <span class="course-dot" :style="{ background: course.color || '#2563eb' }" />
          <span>
            <strong>{{ course.name }}</strong>
            <small>{{ course.semester || '未设置学期' }}</small>
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1500px;
  margin: 0 auto;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 0;
  min-height: calc(100dvh - 96px);
}

.learning-stage {
  padding: 48px 42px 40px 18px;
}

.welcome {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  min-height: 230px;
  padding: 10px 0 28px;
}

.welcome h1 {
  margin: 8px 0 12px;
  font-size: clamp(34px, 4vw, 58px);
  font-weight: 600;
  color: var(--ink);
  line-height: 1.16;
}

.welcome p:not(.eyebrow) {
  color: var(--ink-muted);
  font-size: 15px;
  letter-spacing: 0.06em;
}

.eyebrow,
.section-kicker {
  color: var(--indigo-ink);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

.refresh-button {
  color: var(--ink-muted);
}

.current-learning {
  padding: 28px 6px 30px;
  border-top: 1px solid var(--mineral-line);
  border-bottom: 1px solid var(--mineral-line);
}

.course-focus {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  gap: 30px;
  align-items: center;
  margin-top: 18px;
}

.course-seal {
  min-height: 150px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 24px;
  color: var(--paper);
  background: rgba(18, 45, 59, 0.92);
  background-image: url('../assets/ink-night-texture.webp');
  background-size: cover;
  border-radius: 7px;
  box-shadow: 0 18px 36px rgba(16, 33, 38, 0.14);
}

.course-seal .el-icon { font-size: 25px; color: var(--celadon); }
.course-seal span { font-family: var(--font-display); font-size: 22px; letter-spacing: 0.12em; }
.course-copy h2 { margin: 0; font-size: 32px; color: var(--ink); }
.course-copy > p { margin-top: 7px; color: var(--ink-muted); }
.progress-line { display: grid; grid-template-columns: auto auto minmax(120px, 1fr); gap: 12px; align-items: center; margin-top: 23px; max-width: 520px; color: var(--ink-muted); }
.progress-line strong { color: var(--indigo-ink); font-size: 18px; }
.progress-line :deep(.el-progress-bar__outer) { background: rgba(32, 58, 66, 0.12); }
.course-facts { display: flex; gap: 22px; margin-top: 14px; color: var(--ink-muted); font-size: 12px; }

.next-action {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  margin-top: 30px;
  padding: 20px 22px;
  background: rgba(249, 246, 237, 0.76);
  border: 1px solid var(--mineral-line);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(10px);
}

.next-action-icon,
.guidance-mark {
  width: 46px;
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--ink-night);
  color: var(--celadon);
  font-size: 22px;
}

.next-action h2 { margin: 5px 0 4px; font-size: 20px; }
.next-action-copy > p:last-child { color: var(--ink-muted); font-size: 13px; }

.ai-guidance {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
  margin-top: 22px;
  padding: 22px;
  color: var(--paper);
  background: rgba(9, 27, 35, 0.93);
  background-image: url('../assets/ink-night-texture.webp');
  background-size: cover;
  border: 1px solid rgba(231, 233, 220, 0.12);
  border-radius: 8px;
}

.ai-guidance .section-kicker { color: var(--celadon); }
.ai-guidance h3 { margin: 6px 0; font-family: var(--font-display); font-size: 18px; font-weight: 500; }
.ai-guidance p:last-child { color: rgba(240, 238, 226, 0.62); font-size: 13px; }
.mode-note { margin-top: 8px; padding: 0; border: 0; color: #c7ad79; background: transparent; cursor: pointer; font-size: 11px; }
.ai-guidance .guidance-mark { background: rgba(240, 238, 226, 0.09); }
.ai-guidance :deep(.el-button) { color: var(--paper); border-color: rgba(240, 238, 226, 0.32); background: transparent; }

.tool-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 22px;
  border-top: 1px solid var(--mineral-line);
  border-bottom: 1px solid var(--mineral-line);
}

.tool-strip button {
  min-height: 62px;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  gap: 9px;
  border: 0;
  border-right: 1px solid var(--mineral-line);
  color: var(--ink-soft);
  background: transparent;
  cursor: pointer;
  font: inherit;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.tool-strip button:last-child { border-right: 0; }
.tool-strip button:hover { background: rgba(41, 79, 112, 0.06); color: var(--indigo-ink); }
.tool-strip .el-icon { font-size: 18px; }

.learning-rail {
  padding: 34px 24px;
  color: rgba(240, 238, 226, 0.9);
  background: rgba(8, 25, 33, 0.95);
  background-image: url('../assets/ink-night-texture.webp');
  background-size: cover;
  border-left: 1px solid rgba(230, 231, 218, 0.12);
}

.rail-section { padding: 10px 0 28px; border-bottom: 1px solid rgba(233, 232, 218, 0.12); }
.rail-section + .rail-section { padding-top: 28px; }
.rail-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.rail-heading h2 { display: flex; align-items: center; gap: 8px; font-size: 17px; color: var(--paper); }
.rail-heading :deep(.el-button) { color: var(--celadon); }
.timeline { position: relative; }
.timeline::before { content: ''; position: absolute; left: 8px; top: 8px; bottom: 12px; width: 1px; background: rgba(225, 229, 218, 0.18); }
.timeline-item { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 13px; padding: 0 0 20px; }
.timeline-dot { width: 17px; height: 17px; z-index: 1; border-radius: 50%; border: 2px solid rgba(226, 228, 216, 0.42); background: var(--ink-night); }
.timeline-item.is-completed .timeline-dot { border: 0; color: #9cc1a3; background: transparent; font-size: 18px; }
.timeline-item.is-pending:first-of-type .timeline-dot { border-color: #7f9fc0; box-shadow: 0 0 0 5px rgba(83, 119, 151, 0.13); }
.timeline-item p { color: rgba(234, 233, 220, 0.48); font-size: 11px; }
.timeline-item h3 { margin: 5px 0 6px; color: rgba(249, 247, 236, 0.88); font-size: 13px; font-weight: 500; line-height: 1.5; }
.timeline-item button { padding: 0; border: 0; color: var(--celadon); background: transparent; cursor: pointer; font-size: 11px; }
.timeline-item small { color: #85a88f; }
.rail-empty { color: rgba(234, 233, 220, 0.5); text-align: center; padding: 18px 0; }
.insight-grid { display: grid; grid-template-columns: repeat(3, 1fr); }
.insight-grid div { display: flex; flex-direction: column; gap: 4px; padding: 4px 12px; border-right: 1px solid rgba(230, 231, 218, 0.12); }
.insight-grid div:first-child { padding-left: 0; }
.insight-grid div:last-child { border-right: 0; }
.insight-grid strong { font-family: var(--font-display); font-size: 27px; color: var(--paper); }
.insight-grid span { font-size: 11px; color: rgba(234, 233, 220, 0.48); }
.mastery-progress { margin: 18px 0 13px; }
.mastery-progress > div { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; color: rgba(234, 233, 220, 0.55); font-size: 11px; }
.mastery-progress strong { color: var(--celadon); font-family: var(--font-display); font-size: 16px; font-weight: 500; }
.mastery-progress :deep(.el-progress-bar__outer) { background: rgba(234, 233, 220, 0.1); }
.mastery-progress :deep(.el-progress-bar__inner) { background: #7fae9d; }
.insight-note { color: rgba(234, 233, 220, 0.48); font-size: 11px; line-height: 1.7; }
.run-list { display: grid; gap: 14px; }
.run-list article { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.run-list div { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.run-list strong { overflow: hidden; color: rgba(249, 247, 236, 0.85); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.run-list small { color: rgba(234, 233, 220, 0.42); font-size: 10px; }
.run-status { width: 7px; height: 7px; border-radius: 50%; background: #78848a; }
.run-status.is-succeeded, .run-status.is-success { background: #85aa91; box-shadow: 0 0 0 4px rgba(133, 170, 145, 0.1); }
.run-status.is-failed { background: #c57a6e; }
.run-status.is-running, .run-status.is-started { background: #c7a76c; animation: ink-breathe 2s ease-in-out infinite; }

.mock-banner { margin: 16px 0 0; }
.quick-course-list { display: grid; gap: 10px; }
.quick-course-option {
  min-height: 64px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  background: rgba(250, 248, 240, 0.8);
  color: var(--text-primary);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.quick-course-option:hover {
  border-color: var(--color-primary);
  background: var(--bg-hover);
}

.quick-course-option > span:nth-child(2) {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quick-course-option small {
  color: var(--text-secondary);
}

.course-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

@media (max-width: 1180px) {
  .dashboard-grid { grid-template-columns: minmax(0, 1fr) 290px; }
  .learning-stage { padding-right: 28px; }
}

@media (max-width: 980px) {
  .dashboard-grid { grid-template-columns: minmax(0, 1fr); }
  .learning-rail { margin: 0 -12px -20px; border-left: 0; }
}

@media (max-width: 768px) {
  .learning-stage { padding: 28px 0; }
  .welcome { min-height: 180px; }
  .welcome h1 { font-size: 36px; }
  .refresh-button { display: none; }
  .course-focus { grid-template-columns: 104px minmax(0, 1fr); gap: 18px; }
  .course-seal { min-height: 112px; padding: 16px; }
  .course-copy h2 { font-size: 24px; }
  .progress-line { grid-template-columns: auto auto; }
  .progress-line :deep(.el-progress) { grid-column: 1 / -1; }
  .course-facts { flex-wrap: wrap; gap: 8px 16px; }
  .next-action, .ai-guidance { grid-template-columns: auto minmax(0, 1fr); }
  .next-action :deep(.el-button), .ai-guidance :deep(.el-button) { grid-column: 1 / -1; width: 100%; }
  .tool-strip { grid-template-columns: repeat(2, 1fr); }
  .tool-strip button:nth-child(2) { border-right: 0; }
  .tool-strip button:nth-child(-n+2) { border-bottom: 1px solid var(--mineral-line); }
}
</style>
