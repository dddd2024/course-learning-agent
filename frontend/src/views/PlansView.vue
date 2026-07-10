<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { listCourses, type Course } from '../api/course'
import {
  createPlan,
  type PlanGoal,
  type PlanPayload,
  type PlanResult,
  type PlanTask,
  type Todo,
} from '../api/plan'
import { MAX_PAGE_SIZE } from '../constants/pagination'
import { parseApiError } from '../utils/error'

const router = useRouter()

const courses = ref<Course[]>([])
const coursesLoading = ref(false)
const submitting = ref(false)

const formRef = ref<FormInstance>()

const defaultForm = (): PlanPayload => ({
  goal: '',
  courses: [],
  deadline: '',
  daily_minutes: 60,
})

const form = reactive<PlanPayload>(defaultForm())

const deadlineDate = computed<Date | undefined>({
  get() {
    return form.deadline ? new Date(form.deadline) : undefined
  },
  set(val) {
    form.deadline = val ? toDateString(val) : ''
  },
})

const formRules: FormRules<typeof form> = {
  goal: [
    { required: true, message: '请输入学习目标', trigger: 'blur' },
    { min: 2, max: 200, message: '目标 2-200 字', trigger: 'blur' },
  ],
  courses: [
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

const calendarDate = ref<Date>(new Date())

const todosByDate = computed<Record<string, Todo[]>>(() => {
  const map: Record<string, Todo[]> = {}
  for (const t of todos.value) {
    const key = t.scheduled_date
    if (!map[key]) map[key] = []
    map[key].push(t)
  }
  return map
})

const sortedDates = computed<string[]>(() => {
  return Object.keys(todosByDate.value).sort()
})

function toDateString(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function disablePastDate(date: Date): boolean {
  return date.getTime() < Date.now() - 24 * 60 * 60 * 1000
}

function formatTime(time: string | null): string {
  if (!time) return ''
  // 兼容 "HH:MM:SS" / "HH:MM"
  return time.length >= 5 ? time.slice(0, 5) : time
}

const priorityTagType: Record<string, 'danger' | 'warning' | 'info'> = {
  high: 'danger',
  medium: 'warning',
  low: 'info',
}

function priorityLabel(p: string): string {
  const map: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return map[p] || p
}

const statusTagType: Record<string, 'warning' | 'success' | 'info'> = {
  pending: 'warning',
  completed: 'success',
  postponed: 'info',
}

const statusLabel: Record<string, string> = {
  pending: '待完成',
  completed: '已完成',
  postponed: '已延期',
}

const dayTodosDialogVisible = ref(false)
const dayTodosFor = ref<Todo[]>([])

function getTodosForDay(day: string): Todo[] {
  return todosByDate.value[day] ?? []
}

function showDayTodos(day: string) {
  dayTodosFor.value = getTodosForDay(day)
  dayTodosDialogVisible.value = true
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
      courses: form.courses,
      deadline: form.deadline,
      daily_minutes: form.daily_minutes,
    })
    planResult.value = data
    goal.value = data.goal
    tasks.value = data.tasks
    todos.value = data.todos
    if (data.todos.length > 0) {
      const firstDate = data.todos[0].scheduled_date
      calendarDate.value = new Date(firstDate)
    }
    ElMessage.success('学习计划已生成')
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成计划失败'))
  } finally {
    submitting.value = false
  }
}

function handleReset() {
  planResult.value = null
  goal.value = null
  tasks.value = []
  todos.value = []
  Object.assign(form, defaultForm())
}

onMounted(() => {
  fetchCourses()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">学习计划</h2>
      <div class="toolbar-actions">
        <el-button type="primary" @click="router.push('/plans/multi')">
          多课程规划
        </el-button>
        <el-button v-if="planResult" @click="handleReset">重新规划</el-button>
      </div>
    </div>

    <el-empty
      v-if="!planResult"
      description="填写学习目标，生成专属学习计划与每日待办"
    />

    <el-card v-if="!planResult" class="section-card" shadow="never">
      <template #header>
        <div class="section-title">设定学习目标</div>
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
        <el-form-item label="选择课程" prop="courses">
          <el-select
            v-model="form.courses"
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
              :value="c.name"
            />
          </el-select>
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="截止日期" prop="deadline">
              <el-date-picker
                v-model="deadlineDate"
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
            生成学习计划
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <template v-if="planResult">
      <el-card v-if="goal" class="section-card" shadow="never">
        <template #header>
          <div class="section-title-bar">
            <span class="section-title">学习目标</span>
            <el-tag :type="goal.status === 'completed' ? 'success' : 'warning'">
              {{ goal.status === 'completed' ? '已完成' : '进行中' }}
            </el-tag>
          </div>
        </template>
        <div class="goal-info">
          <div class="goal-title">{{ goal.title }}</div>
          <div class="goal-meta">
            <span>截止日期：{{ goal.deadline }}</span>
            <span>每日时间：{{ goal.daily_minutes }} 分钟</span>
            <span>阶段任务：{{ tasks.length }} 个</span>
            <span>每日待办：{{ todos.length }} 条</span>
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
          <el-table-column prop="course_name" label="课程" min-width="140" show-overflow-tooltip />
          <el-table-column prop="title" label="任务标题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="task_type" label="类型" width="110" />
          <el-table-column prop="estimate_minutes" label="预计分钟" width="100" align="center" />
          <el-table-column label="优先级" width="90" align="center">
            <template #default="{ row }">
              <el-tag
                :type="priorityTagType[row.priority] || 'info'"
                size="small"
              >
                {{ priorityLabel(row.priority) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="acceptance" label="完成标准" min-width="220" show-overflow-tooltip />
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
              </div>
            </div>
          </div>
        </div>
      </el-card>
    </template>

    <el-dialog v-model="dayTodosDialogVisible" title="当日待办" width="500">
      <ul class="day-todo-list">
        <li v-for="t in dayTodosFor" :key="t.id" class="day-todo-item">
          <span>{{ t.title }}</span>
          <el-tag size="small" :type="statusTagType[t.status]">{{ statusLabel[t.status] }}</el-tag>
        </li>
      </ul>
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

.section-card {
  margin-bottom: 20px;
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
</style>
