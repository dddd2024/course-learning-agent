<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { listCourses, type Course } from '../api/course'
import {
  createPlan,
  deletePlan,
  getPlan,
  listPlans,
  updateGoal,
  updateTodo,
  startTask,
  retryTask,
  overrideTask,
  type PlanGoal,
  type PlanPayload,
  type PlanResult,
  type PlanSummary,
  type PlanTask,
  type Todo,
} from '../api/plan'
import { MAX_PAGE_SIZE } from '../constants/pagination'
import { formatLocalDateTime } from '../utils/datetime'
import { parseApiError } from '../utils/error'

const route = useRoute()
const router = useRouter()

const courses = ref<Course[]>([])
const coursesLoading = ref(false)
const plans = ref<PlanSummary[]>([])
const plansLoading = ref(false)
const planLoading = ref(false)
const submitting = ref(false)
const isCreating = ref(false)
const selectedPlanId = ref<number | null>(null)

const formRef = ref<FormInstance>()

const defaultForm = (): PlanPayload => ({
  goal: '',
  course_ids: [],
  deadline: '',
  daily_minutes: 60,
})

const form = reactive<PlanPayload>(defaultForm())

const formRules: FormRules<typeof form> = {
  goal: [
    { required: true, message: '请输入学习目标', trigger: 'blur' },
    { min: 2, max: 200, message: '目标 2-200 字', trigger: 'blur' },
  ],
  course_ids: [
    {
      required: true,
      type: 'array',
      min: 1,
      message: '请至少选择一门课程',
      trigger: 'change',
    },
  ],
  deadline: [{ required: true, message: '请选择截止日期', trigger: 'change' }],
  daily_minutes: [
    { required: true, type: 'number', min: 10, max: 1440, message: '每日 10-1440 分钟', trigger: 'blur' },
  ],
}

const planResult = ref<PlanResult | null>(null)
const goal = ref<PlanGoal | null>(null)
const tasks = ref<PlanTask[]>([])
const todos = ref<Todo[]>([])

// PLAN-V3-02/03: task execution state
const taskStarting = ref<number | null>(null)
const overrideDialogVisible = ref(false)
const overrideReason = ref('')
const overrideTaskId = ref<number | null>(null)
const overrideLoading = ref(false)

const calendarDate = ref<Date>(new Date())

const selectedSummary = computed<PlanSummary | null>(() => {
  return plans.value.find((plan) => plan.goal.id === selectedPlanId.value) ?? null
})

const selectedProgress = computed(() => {
  const progress = selectedSummary.value?.progress
  if (!progress) return 0
  if (progress.todos_total > 0) {
    return Math.round((progress.todos_completed / progress.todos_total) * 100)
  }
  if (progress.tasks_total > 0) {
    return Math.round((progress.tasks_completed / progress.tasks_total) * 100)
  }
  return 0
})

const todosByDate = computed<Record<string, Todo[]>>(() => {
  const map: Record<string, Todo[]> = {}
  for (const todo of todos.value) {
    const key = todo.scheduled_date
    if (!map[key]) map[key] = []
    map[key].push(todo)
  }
  return map
})

const sortedDates = computed<string[]>(() => Object.keys(todosByDate.value).sort())

function disablePastDate(date: Date): boolean {
  return date.getTime() < Date.now() - 24 * 60 * 60 * 1000
}

function formatTime(time: string | null): string {
  if (!time) return ''
  return time.length >= 5 ? time.slice(0, 5) : time
}

function formatPlanLabel(plan: PlanSummary): string {
  const courseText = plan.course_names.filter(Boolean).join('、') || '未关联课程'
  return `${plan.goal.title} · ${courseText}`
}

function goalStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    active: '进行中',
    done: '已完成',
    completed: '已完成',
    archived: '已归档',
  }
  return labels[status] || status
}

function goalStatusType(status: string): 'success' | 'warning' | 'info' {
  if (status === 'done' || status === 'completed') return 'success'
  if (status === 'archived') return 'info'
  return 'warning'
}

function priorityLabel(priority: number): string {
  const labels: Record<number, string> = {
    5: '最高',
    4: '高',
    3: '中',
    2: '低',
    1: '最低',
  }
  return labels[priority] || String(priority)
}

function priorityTagType(priority: number): 'danger' | 'warning' | 'info' {
  if (priority >= 5) return 'danger'
  if (priority >= 3) return 'warning'
  return 'info'
}

function taskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    review: '复习',
    learn: '学习',
    quiz: '测验',
  }
  return labels[taskType] || taskType
}

// PLAN-V3-03: execution status helpers
function executionStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '待开始',
    in_progress: '进行中',
    completed: '已完成',
  }
  return labels[status] || status
}

function executionStatusTagType(status: string): 'info' | 'warning' | 'success' {
  if (status === 'completed') return 'success'
  if (status === 'in_progress') return 'warning'
  return 'info'
}

function verificationMethodLabel(method: string | null): string {
  if (!method) return ''
  const labels: Record<string, string> = {
    quiz_score: '测验分数',
    score_threshold: '分数达标',
    reading_completion: '阅读完成',
    kp_viewed: '知识点已查看',
    manual_override: '手动覆盖',
    manual: '手动确认',
  }
  return labels[method] || method
}

/**
 * Determine the primary action button label for a task based on its
 * type and execution status.
 */
function taskActionButton(task: PlanTask): { label: string; type: 'primary' | 'success' | 'default' } {
  if (task.execution_status === 'completed' || task.status === 'done') {
    if (task.target_type === 'quiz' && task.target_id) {
      return { label: '查看结果', type: 'default' }
    }
    return { label: '已完成', type: 'default' }
  }
  if (task.target_type === 'quiz' && task.target_id) {
    return { label: '继续测验', type: 'primary' }
  }
  if (task.task_type === 'quiz') {
    return { label: '生成测验', type: 'primary' }
  }
  if (task.task_type === 'learn') {
    return { label: '开始学习', type: 'primary' }
  }
  if (task.task_type === 'review') {
    return { label: '复习知识点', type: 'primary' }
  }
  return { label: '开始', type: 'primary' }
}

/** Whether the task shows a "重新练习" button alongside "查看结果". */
function canRetryTask(task: PlanTask): boolean {
  return (
    (task.execution_status === 'completed' || task.status === 'done') &&
    task.task_type === 'quiz'
  )
}

/** Whether the task can be manually overridden (not yet completed). */
function canOverrideTask(task: PlanTask): boolean {
  return task.execution_status !== 'completed' && task.status !== 'done'
}

/** Whether to show a verification tip for insufficient evidence quizzes. */
function hasInsufficientEvidence(task: PlanTask): boolean {
  if (!task.verification_result) return false
  return Boolean(task.verification_result.insufficient_evidence)
}

const statusTagType: Record<string, 'warning' | 'success' | 'info'> = {
  pending: 'warning',
  completed: 'success',
  postponed: 'info',
  skipped: 'info',
}

const statusLabel: Record<string, string> = {
  pending: '待完成',
  completed: '已完成',
  postponed: '已延期',
  skipped: '已跳过',
}

const dayTodosDialogVisible = ref(false)
const dayTodosFor = ref<Todo[]>([])

function showDayTodos(day: string) {
  dayTodosFor.value = todosByDate.value[day] ?? []
  dayTodosDialogVisible.value = true
}

function applyPlan(data: PlanResult) {
  planResult.value = data
  goal.value = data.goal
  tasks.value = data.tasks
  todos.value = data.todos
  const focusDate = data.todos[0]?.scheduled_date || data.goal.deadline
  if (focusDate) calendarDate.value = new Date(`${focusDate}T00:00:00`)
}

async function syncPlanQuery(planId: number) {
  if (String(route.query.plan_id ?? '') === String(planId)) return
  await router.replace({
    query: { ...route.query, plan_id: String(planId) },
  })
}

async function loadSavedPlan(planId: number, updateQuery = true) {
  planLoading.value = true
  try {
    const { data } = await getPlan(planId)
    applyPlan(data)
    selectedPlanId.value = planId
    isCreating.value = false
    if (updateQuery) await syncPlanQuery(planId)
    // Persist the plan ID so it can be restored when returning from
    // quiz/learn pages (where the plan_id query param is lost).
    sessionStorage.setItem('plans:lastPlanId', String(planId))
  } catch (err) {
    ElMessage.error(parseApiError(err, '读取学习计划失败'))
  } finally {
    planLoading.value = false
  }
}

async function restorePlans(preferredId?: number) {
  plansLoading.value = true
  try {
    const { data } = await listPlans()
    plans.value = data.items
    if (data.items.length === 0) {
      selectedPlanId.value = null
      planResult.value = null
      goal.value = null
      tasks.value = []
      todos.value = []
      isCreating.value = true
      return
    }

    const queryId = Number(route.query.plan_id)
    const storedId = Number(sessionStorage.getItem('plans:lastPlanId'))
    const requestedId = preferredId || (Number.isInteger(queryId) ? queryId : 0) || (Number.isInteger(storedId) ? storedId : 0)
    const target =
      data.items.find((plan) => plan.goal.id === requestedId)
      ?? data.items.find((plan) => plan.goal.status === 'active')
      ?? data.items[0]
    await loadSavedPlan(target.goal.id)
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取已保存计划失败'))
    if (!planResult.value) isCreating.value = true
  } finally {
    plansLoading.value = false
  }
}

async function fetchCourses() {
  coursesLoading.value = true
  try {
    const { data } = await listCourses({ page: 1, page_size: MAX_PAGE_SIZE })
    courses.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取课程列表失败'))
  } finally {
    coursesLoading.value = false
  }
}

async function handlePlanSelect(planId: number) {
  if (planId === selectedPlanId.value && !isCreating.value) return
  await loadSavedPlan(planId)
}

function startNewPlan() {
  Object.assign(form, defaultForm())
  const requestedCourseId = Number(route.query.course_id)
  if (courses.value.some((course) => course.id === requestedCourseId)) {
    form.course_ids = [requestedCourseId]
  }
  formRef.value?.clearValidate()
  isCreating.value = true
}

function returnToSavedPlan() {
  if (selectedPlanId.value) isCreating.value = false
}

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const { data } = await createPlan({
      goal: form.goal,
      course_ids: form.course_ids,
      deadline: form.deadline,
      daily_minutes: form.daily_minutes,
    })
    applyPlan(data)
    selectedPlanId.value = data.goal.id
    isCreating.value = false
    await syncPlanQuery(data.goal.id)
    await restorePlans(data.goal.id)
    ElMessage.success('新学习计划已保存，原有计划仍保留')
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成计划失败'))
  } finally {
    submitting.value = false
  }
}

// PLAN-V3-02/03: Task execution handlers
async function handleStartTask(task: PlanTask) {
  taskStarting.value = task.id
  try {
    const { data } = await startTask(task.id)
    if (!data.route_name && data.quiz_id) {
      await router.push({ path: '/quizzes', query: { course_id: task.course_id, task_id: String(task.id), quiz_id: String(data.quiz_id) } })
      return
    }
    const query = { ...data.route_params, task_id: String(task.id), plan_id: String(task.goal_id) } as Record<string, string>
    if (data.route_name === 'quizzes') query.course_id = String(task.course_id)
    await router.push({ name: data.route_name, params: data.route_name === 'quizzes' ? {} : { id: String(task.course_id) }, query })
  } catch (err) {
    ElMessage.error(parseApiError(err, '启动任务失败'))
  } finally {
    taskStarting.value = null
  }
}

async function handleRetryTask(task: PlanTask) {
  // For completed quiz tasks: start a new quiz
  taskStarting.value = task.id
  try {
    const { data } = await retryTask(task.id)
    if (data.quiz_id) {
      router.push({
        path: '/quizzes',
        query: {
          course_id: task.course_id,
          task_id: String(task.id),
          quiz_id: String(data.quiz_id),
        },
      })
    } else {
      await loadSavedPlan(task.goal_id)
      ElMessage.success('已生成新测验')
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '重新练习失败'))
  } finally {
    taskStarting.value = null
  }
}

async function handleViewResult(task: PlanTask) {
  if (task.target_type === 'quiz' && task.target_id) {
    router.push({
      path: '/quizzes',
      query: {
        course_id: task.course_id,
        task_id: String(task.id),
        quiz_id: String(task.target_id),
      },
    })
  }
}

function openOverrideDialog(task: PlanTask) {
  overrideTaskId.value = task.id
  overrideReason.value = ''
  overrideDialogVisible.value = true
}

async function handleOverride() {
  if (!overrideTaskId.value || !overrideReason.value.trim()) return
  overrideLoading.value = true
  try {
    await overrideTask(overrideTaskId.value, overrideReason.value.trim())
    ElMessage.success('任务已手动覆盖为完成')
    overrideDialogVisible.value = false
    await loadSavedPlan(selectedPlanId.value ?? overrideTaskId.value)
    await restorePlans(selectedPlanId.value ?? undefined)
  } catch (err) {
    ElMessage.error(parseApiError(err, '手动覆盖失败'))
  } finally {
    overrideLoading.value = false
  }
}

async function toggleTodoStatus(todo: Todo) {
  const newStatus = todo.status === 'completed' ? 'pending' : 'completed'
  try {
    const { data: updated } = await updateTodo(todo.id, { status: newStatus })
    const idx = todos.value.findIndex((t) => t.id === todo.id)
    if (idx >= 0) todos.value[idx] = updated
    ElMessage.success(newStatus === 'completed' ? '待办已完成' : '待办已恢复')
    await restorePlans(selectedPlanId.value ?? undefined)
  } catch (err) {
    ElMessage.error(parseApiError(err, '更新待办状态失败'))
  }
}

async function handleDeletePlan() {
  if (!selectedPlanId.value) return
  try {
    await ElMessageBox.confirm('确定要删除该学习计划吗？关联的任务和待办也将被删除。', '删除计划', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deletePlan(selectedPlanId.value)
    ElMessage.success('计划已删除')
    selectedPlanId.value = null
    planResult.value = null
    goal.value = null
    tasks.value = []
    todos.value = []
    await restorePlans()
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除计划失败'))
  }
}

async function handleCompleteGoal() {
  if (!goal.value) return
  try {
    const { data: updated } = await updateGoal(goal.value.id, { status: 'done' })
    goal.value = updated
    ElMessage.success('学习计划已标记完成')
    await restorePlans(updated.id)
  } catch (err) {
    ElMessage.error(parseApiError(err, '更新计划状态失败'))
  }
}

onMounted(async () => {
  await fetchCourses()
  await restorePlans()
  if (Number.isInteger(Number(route.query.course_id))) startNewPlan()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h2 class="title">学习计划</h2>
        <p class="page-intro">打开即可继续上次计划，也可以另存一份新计划。</p>
      </div>
      <div class="toolbar-actions">
        <el-button @click="router.push('/plans/multi')">
          多课程规划
        </el-button>
        <el-button
          v-if="!isCreating"
          type="primary"
          @click="startNewPlan"
        >
          新建计划
        </el-button>
        <el-button
          v-else-if="selectedPlanId"
          @click="returnToSavedPlan"
        >
          返回已保存计划
        </el-button>
      </div>
    </div>

    <el-card
      v-if="plans.length > 0"
      class="section-card plan-picker-card"
      shadow="never"
      v-loading="plansLoading"
    >
      <div class="plan-picker">
        <div class="plan-picker-control">
          <label class="picker-label" for="saved-plan-select">已保存计划</label>
          <el-select
            id="saved-plan-select"
            :model-value="selectedPlanId"
            filterable
            :disabled="planLoading"
            placeholder="选择要查看的计划"
            @change="handlePlanSelect"
          >
            <el-option
              v-for="plan in plans"
              :key="plan.goal.id"
              :label="formatPlanLabel(plan)"
              :value="plan.goal.id"
            >
              <div class="plan-option">
                <span class="plan-option-title">{{ plan.goal.title }}</span>
                <span class="plan-option-meta">
                  {{ plan.course_names.filter(Boolean).join('、') || '未关联课程' }}
                  · 待办 {{ plan.progress.todos_completed }}/{{ plan.progress.todos_total }}
                </span>
              </div>
            </el-option>
          </el-select>
        </div>
        <div v-if="selectedSummary" class="plan-picker-progress">
          <div class="progress-copy">
            <span>待办进度 {{ selectedSummary.progress.todos_completed }}/{{ selectedSummary.progress.todos_total }}</span>
            <strong>{{ selectedProgress }}%</strong>
          </div>
          <el-progress :percentage="selectedProgress" :show-text="false" :stroke-width="8" />
          <span class="saved-at">创建于 {{ formatLocalDateTime(selectedSummary.created_at) }}</span>
        </div>
      </div>
    </el-card>

    <el-card
      v-if="isCreating"
      class="section-card"
      shadow="never"
      v-loading="plansLoading && plans.length === 0"
    >
      <template #header>
        <div>
          <div class="section-title">创建新学习计划</div>
          <div class="section-tip form-tip">新计划会单独保存，不会覆盖或删除已有计划。</div>
        </div>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-position="top"
        v-loading="coursesLoading"
      >
        <el-form-item label="学习目标" prop="goal">
          <el-input
            v-model="form.goal"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="如：7 天复习完操作系统"
          />
        </el-form-item>
        <el-form-item label="选择课程" prop="course_ids">
          <el-select
            v-model="form.course_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="请选择课程"
            style="width: 100%"
          >
            <el-option
              v-for="c in courses"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="截止日期" prop="deadline">
              <el-date-picker
                v-model="form.deadline"
                type="date"
                placeholder="选择截止日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                :disabled-date="disablePastDate"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="每日可用时间（分钟）" prop="daily_minutes">
              <el-input-number
                v-model="form.daily_minutes"
                :min="10"
                :max="1440"
                :step="10"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            @click="handleSubmit"
          >
            生成并保存计划
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div v-else v-loading="planLoading" class="plan-detail-loading">
      <template v-if="planResult">
        <el-alert
          v-if="planResult.unscheduled_tasks?.length"
          type="warning"
          :closable="false"
          class="plan-unscheduled"
          :title="`有 ${planResult.unscheduled_tasks.length} 项未排入计划`"
          :description="planResult.unscheduled_tasks.map((t) => `${t.title}（${t.estimate_minutes} 分钟）：${t.suggestion}`).join('；')"
          show-icon
        />
      <el-card v-if="goal" class="section-card" shadow="never">
        <template #header>
          <div class="section-title-bar">
            <span class="section-title">学习目标</span>
            <div class="header-actions">
              <el-tag :type="goalStatusType(goal.status)">
                {{ goalStatusLabel(goal.status) }}
              </el-tag>
              <el-button
                v-if="goal.status !== 'done'"
                type="success"
                size="small"
                plain
                @click="handleCompleteGoal"
              >
                标记完成
              </el-button>
              <el-button
                type="danger"
                size="small"
                plain
                @click="handleDeletePlan"
              >
                删除计划
              </el-button>
            </div>
          </div>
        </template>
        <div class="goal-info">
          <div class="goal-title">{{ goal.title }}</div>
          <div class="goal-meta">
            <span>截止日期：{{ goal.deadline }}</span>
            <span>每日时间：{{ goal.daily_minutes }} 分钟</span>
            <span>阶段任务：{{ tasks.length }} 个</span>
            <span>每日待办：{{ todos.length }} 条</span>
            <span v-if="selectedSummary">已完成：{{ selectedSummary.progress.todos_completed }} 条</span>
          </div>
        </div>
      </el-card>

      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-title">阶段任务</div>
        </template>
        <el-table
          :data="tasks"
          stripe
          empty-text="暂无阶段任务"
        >
          <el-table-column prop="course_name" label="课程" min-width="120" show-overflow-tooltip />
          <el-table-column prop="title" label="任务标题" min-width="160" show-overflow-tooltip />
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ taskTypeLabel(row.task_type) }}</template>
          </el-table-column>
          <el-table-column prop="estimate_minutes" label="预计分钟" width="90" align="center" />
          <el-table-column label="优先级" width="80" align="center">
            <template #default="{ row }">
              <el-tag
                :type="priorityTagType(row.priority)"
                size="small"
              >
                {{ priorityLabel(row.priority) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="acceptance" label="完成标准" min-width="180" show-overflow-tooltip />
          <el-table-column label="执行状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="executionStatusTagType(row.execution_status)" size="small">
                {{ executionStatusLabel(row.execution_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="验证方式" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.verification_method" class="verify-method">
                {{ verificationMethodLabel(row.verification_method) }}
              </span>
              <span v-else class="verify-method-empty">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center" fixed="right">
            <template #default="{ row }">
              <div class="task-actions">
                <el-button
                  v-if="taskActionButton(row).label !== '已完成'"
                  :type="taskActionButton(row).type"
                  size="small"
                  :loading="taskStarting === row.id"
                  @click="handleStartTask(row)"
                >
                  {{ taskActionButton(row).label }}
                </el-button>
                <el-button
                  v-if="row.execution_status === 'completed' && row.target_type === 'quiz' && row.target_id"
                  size="small"
                  @click="handleViewResult(row)"
                >
                  查看结果
                </el-button>
                <el-button
                  v-if="canRetryTask(row)"
                  size="small"
                  :loading="taskStarting === row.id"
                  @click="handleRetryTask(row)"
                >
                  重新练习
                </el-button>
                <el-button
                  v-if="canOverrideTask(row)"
                  size="small"
                  link
                  type="warning"
                  @click="openOverrideDialog(row)"
                >
                  手动完成
                </el-button>
              </div>
              <div v-if="hasInsufficientEvidence(row)" class="insufficient-tip">
                证据不足，建议先学习相关知识点再生成测验
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-title-bar">
            <span class="section-title">日历视图</span>
            <span class="section-tip">按日期展示每日待办</span>
          </div>
        </template>
        <el-calendar v-model="calendarDate">
          <template #date-cell="{ data }">
            <div class="cal-cell">
              <div class="cal-day">{{ data.day.slice(-2) }}</div>
              <div v-if="todosByDate[data.day]" class="cal-todos">
                <div
                  v-for="t in todosByDate[data.day].slice(0, 3)"
                  :key="t.id"
                  class="cal-todo-item"
                  :class="`cal-todo-${t.status}`"
                >
                  {{ t.title }}
                </div>
                <span
                  v-if="todosByDate[data.day].length > 3"
                  class="overflow-link"
                  @click="showDayTodos(data.day)"
                >
                  +{{ todosByDate[data.day].length - 3 }}
                </span>
              </div>
            </div>
          </template>
        </el-calendar>
      </el-card>

      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-title">列表视图</div>
        </template>
        <el-empty
          v-if="sortedDates.length === 0"
          description="暂无待办"
        />
        <div v-for="date in sortedDates" :key="date" class="date-group">
          <div class="date-header">
            <span class="date-text">{{ date }}</span>
            <span class="date-count">{{ todosByDate[date].length }} 条</span>
          </div>
          <div class="todo-list">
            <div
              v-for="t in todosByDate[date]"
              :key="t.id"
              class="todo-item"
              :class="{ 'todo-done': t.status === 'completed' }"
            >
              <div class="todo-main">
                <el-tag
                  :type="statusTagType[t.status] || 'info'"
                  size="small"
                >
                  {{ statusLabel[t.status] || t.status }}
                </el-tag>
                <span class="todo-title">{{ t.title }}</span>
                <span class="todo-course">{{ t.course_name }}</span>
              </div>
              <div class="todo-meta">
                <span v-if="t.scheduled_start">
                  {{ formatTime(t.scheduled_start) }}
                  <template v-if="t.scheduled_end">
                    - {{ formatTime(t.scheduled_end) }}
                  </template>
                </span>
                <span>{{ t.estimate_minutes }} 分钟</span>
                <el-button
                  :type="t.status === 'completed' ? 'default' : 'success'"
                  size="small"
                  link
                  @click="toggleTodoStatus(t)"
                >
                  {{ t.status === 'completed' ? '撤销完成' : '完成' }}
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </el-card>
      </template>
      <el-empty
        v-else-if="!plansLoading && !planLoading"
        description="还没有可显示的计划，请新建一份学习计划"
      />
    </div>

    <el-dialog v-model="dayTodosDialogVisible" title="当日待办" width="500">
      <ul class="day-todo-list">
        <li v-for="t in dayTodosFor" :key="t.id" class="day-todo-item">
          <div class="day-todo-info">
            <span>{{ t.title }}</span>
            <el-tag size="small" :type="statusTagType[t.status]">{{ statusLabel[t.status] }}</el-tag>
          </div>
          <el-button
            :type="t.status === 'completed' ? 'default' : 'success'"
            size="small"
            link
            @click="toggleTodoStatus(t)"
          >
            {{ t.status === 'completed' ? '撤销完成' : '完成' }}
          </el-button>
        </li>
      </ul>
    </el-dialog>

    <el-dialog
      v-model="overrideDialogVisible"
      title="手动完成任务"
      width="min(480px, calc(100vw - 32px))"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="手动覆盖将跳过验证流程，请确认任务确实已完成。"
        style="margin-bottom: 16px;"
      />
      <el-form label-position="top">
        <el-form-item label="覆盖原因（必填）">
          <el-input
            v-model="overrideReason"
            type="textarea"
            :rows="3"
            placeholder="请输入手动完成的原因，例如：已线下完成、已通过其他方式验证等"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="overrideDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="overrideLoading"
          :disabled="!overrideReason.trim()"
          @click="handleOverride"
        >
          确认覆盖
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  background: #fff;
  padding: 24px;
  border-radius: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title {
  font-size: 20px;
  margin: 0;
  color: #303133;
}

.page-intro {
  margin: 6px 0 0;
  color: #909399;
  font-size: 13px;
}

.section-card {
  margin-bottom: 20px;
}

.plan-picker-card {
  background: #f8fbff;
  border-color: #d9ecff;
}

.plan-picker {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(220px, 320px);
  align-items: end;
  gap: 28px;
}

.plan-picker-control {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-picker-control :deep(.el-select) {
  width: 100%;
}

.picker-label {
  color: #303133;
  font-size: 14px;
  font-weight: 600;
}

.plan-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.plan-option-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-option-meta {
  flex: none;
  color: #909399;
  font-size: 12px;
}

.plan-picker-progress {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.progress-copy {
  display: flex;
  justify-content: space-between;
  color: #606266;
  font-size: 13px;
}

.progress-copy strong {
  color: #303133;
}

.saved-at {
  color: #909399;
  font-size: 12px;
}

.form-tip {
  margin-top: 6px;
}

.plan-detail-loading {
  min-height: 160px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.section-title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.todo-done .todo-title {
  text-decoration: line-through;
  color: #909399;
}

.day-todo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
}

.day-todo-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-tip {
  font-size: 13px;
  color: #909399;
}

.goal-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.goal-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.goal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #606266;
}

.cal-cell {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 2px;
}

.cal-day {
  font-size: 13px;
  color: #606266;
  text-align: right;
  padding: 0 4px;
}

.cal-todos {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px;
}

.cal-todo-item {
  font-size: 12px;
  color: #fff;
  background-color: #409eff;
  padding: 1px 4px;
  border-radius: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cal-todo-completed {
  background-color: #67c23a;
  text-decoration: line-through;
}

.cal-todo-postponed {
  background-color: #909399;
  text-decoration: line-through;
}

.cal-more {
  font-size: 12px;
  color: #909399;
  padding: 0 4px;
}

.overflow-link {
  color: #409eff;
  cursor: pointer;
  font-size: 12px;
  padding: 0 4px;
}

.overflow-link:hover {
  text-decoration: underline;
}

.day-todo-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.day-todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.date-group {
  margin-bottom: 16px;
}

.date-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
}

.date-text {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.date-count {
  font-size: 13px;
  color: #909399;
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.todo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.todo-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.todo-title {
  font-size: 14px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo-course {
  font-size: 13px;
  color: #909399;
}

.todo-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}

@media (max-width: 768px) {
  .page {
    padding: 16px;
  }

  .toolbar {
    align-items: flex-start;
    flex-direction: column;
    gap: 14px;
  }

  .toolbar-actions {
    width: 100%;
  }

  .toolbar-actions :deep(.el-button) {
    flex: 1;
    margin-left: 0;
  }

  .plan-picker {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .plan-option-meta {
    display: none;
  }

  .todo-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .todo-main {
    width: 100%;
  }

  .todo-course {
    display: none;
  }
}

/* PLAN-V3-03: task execution UI */
.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: center;
}

.verify-method {
  font-size: 12px;
  color: #606266;
}

.verify-method-empty {
  color: #c0c4cc;
}

.insufficient-tip {
  margin-top: 4px;
  font-size: 12px;
  color: #e6a23c;
  line-height: 1.4;
}
</style>
