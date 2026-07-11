<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCourses, type Course } from '../api/course'
import {
  listTodos,
  updateTodo,
  type Todo,
  type TodoStatus,
} from '../api/plan'
import { MAX_PAGE_SIZE } from '../constants/pagination'
import { parseApiError } from '../utils/error'
import EmptyState from '../components/common/EmptyState.vue'

const router = useRouter()

const courses = ref<Course[]>([])
const coursesLoading = ref(false)

const todayTodos = ref<Todo[]>([])
const todayLoading = ref(false)

const allTodos = ref<Todo[]>([])
const allTotal = ref(0)
const allLoading = ref(false)

const query = reactive({
  date: '' as string,
  status: '' as TodoStatus | '',
  course_id: undefined as number | undefined,
  page: 1,
  page_size: 10,
})

const queryDate = computed<Date | undefined>({
  get() {
    return query.date ? new Date(query.date) : undefined
  },
  set(val) {
    query.date = val ? toDateString(val) : ''
  },
})

const statusOptions: { label: string; value: TodoStatus | '' }[] = [
  { label: '全部', value: '' },
  { label: '待完成', value: 'pending' },
  { label: '已完成', value: 'completed' },
  { label: '已延期', value: 'postponed' },
]

const statusTagType: Record<TodoStatus, 'warning' | 'success' | 'info'> = {
  pending: 'warning',
  completed: 'success',
  postponed: 'info',
}

const statusLabel: Record<TodoStatus, string> = {
  pending: '待完成',
  completed: '已完成',
  postponed: '已延期',
}

const courseColors = new Map<string, string>()
function getCourseColor(courseName: string): string {
  const course = courses.value.find((c) => c.name === courseName)
  if (course?.color) return course.color
  // Fallback to hash-based color if course not found or no color
  if (courseColors.has(courseName)) return courseColors.get(courseName)!
  const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9b59b6', '#1abc9c']
  const idx = courseColors.size % colors.length
  courseColors.set(courseName, colors[idx])
  return colors[idx]
}

const recordDialogVisible = ref(false)
const recordLoading = ref(false)
const recordTarget = ref<Todo | null>(null)
const recordForm = reactive({
  actual_minutes: 0,
})

const batchLoading = ref(false)

function toDateString(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function todayString(): string {
  return toDateString(new Date())
}

function isOverdue(todo: Todo): boolean {
  if (todo.status !== 'pending') return false
  if (!todo.scheduled_date) return false
  return todo.scheduled_date < todayString()
}

function tableRowClassName({ row }: { row: Todo }): string {
  return isOverdue(row) ? 'overdue-row' : ''
}

function formatTime(time: string | null): string {
  if (!time) return ''
  return time.length >= 5 ? time.slice(0, 5) : time
}

function formatDateTime(dt: string | null): string {
  if (!dt) return ''
  try {
    return new Date(dt).toLocaleString()
  } catch {
    return dt
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

async function fetchTodayTodos() {
  todayLoading.value = true
  try {
    const { data } = await listTodos({ date: todayString() })
    todayTodos.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取今日待办失败'))
  } finally {
    todayLoading.value = false
  }
}

async function fetchAllTodos() {
  allLoading.value = true
  try {
    const { data } = await listTodos({
      date: query.date || undefined,
      status: query.status || undefined,
      course_id: query.course_id,
      page: query.page,
      page_size: query.page_size,
    })
    allTodos.value = data.items
    allTotal.value = data.total
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取待办列表失败'))
  } finally {
    allLoading.value = false
  }
}

function handleFilterChange() {
  query.page = 1
  fetchAllTodos()
}

function handlePageChange(page: number) {
  query.page = page
  fetchAllTodos()
}

function handlePageSizeChange(size: number) {
  query.page_size = size
  query.page = 1
  fetchAllTodos()
}

function applyTodoUpdate(updated: Todo) {
  const updateIn = (list: Todo[]) => {
    const idx = list.findIndex((t) => t.id === updated.id)
    if (idx >= 0) list[idx] = { ...list[idx], ...updated }
  }
  updateIn(todayTodos.value)
  updateIn(allTodos.value)
}

async function handleComplete(todo: Todo) {
  const nextStatus: TodoStatus = todo.status === 'completed' ? 'pending' : 'completed'
  try {
    const { data } = await updateTodo(todo.id, { status: nextStatus })
    applyTodoUpdate(data)
    ElMessage.success(nextStatus === 'completed' ? '已完成' : '已恢复为待完成')
  } catch (err) {
    ElMessage.error(parseApiError(err, nextStatus === 'completed' ? '完成待办失败' : '恢复待办失败'))
  }
}

async function handleBatchComplete() {
  const pendingTodos = todayTodos.value.filter((t) => t.status === 'pending')
  if (pendingTodos.length === 0) {
    ElMessage.info('没有待完成的待办')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定将 ${pendingTodos.length} 个待办全部标记为完成吗？`,
      '批量完成',
      { type: 'warning', confirmButtonText: '全部完成', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchLoading.value = true
  try {
    const results = await Promise.all(
      pendingTodos.map((t) => updateTodo(t.id, { status: 'completed' })),
    )
    results.forEach(({ data }) => applyTodoUpdate(data))
    ElMessage.success(`已完成 ${results.length} 个待办`)
  } catch (err) {
    ElMessage.error(parseApiError(err, '批量完成失败'))
  } finally {
    batchLoading.value = false
  }
}

function goToCourse(todo: Todo) {
  if (todo.course_id) {
    router.push(`/courses/${todo.course_id}/learn`)
  }
}

async function handlePostpone(todo: Todo) {
  if (todo.status === 'postponed') {
    try {
      const { data } = await updateTodo(todo.id, { status: 'pending' })
      applyTodoUpdate(data)
      ElMessage.success('已恢复为待完成')
    } catch (err) {
      ElMessage.error(parseApiError(err, '恢复待办失败'))
    }
    return
  }
  try {
    await ElMessageBox.confirm(
      `暂缓「${todo.title}」会保留原计划日期，并标记为已暂缓。稍后可恢复。`,
      '暂缓待办',
      { type: 'warning', confirmButtonText: '确认暂缓', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const { data } = await updateTodo(todo.id, { status: 'postponed' })
    applyTodoUpdate(data)
    ElMessage.success('已暂缓，可随时恢复')
  } catch (err) {
    ElMessage.error(parseApiError(err, '延期待办失败'))
  }
}

function openRecordDialog(todo: Todo) {
  recordTarget.value = todo
  recordForm.actual_minutes = todo.actual_minutes ?? todo.estimate_minutes ?? 0
  recordDialogVisible.value = true
}

async function handleRecordSubmit() {
  if (!recordTarget.value) return
  recordLoading.value = true
  try {
    const { data } = await updateTodo(recordTarget.value.id, {
      actual_minutes: recordForm.actual_minutes,
    })
    applyTodoUpdate(data)
    ElMessage.success('已记录实际时长')
    recordDialogVisible.value = false
  } catch (err) {
    ElMessage.error(parseApiError(err, '记录失败'))
  } finally {
    recordLoading.value = false
  }
}

onMounted(() => {
  fetchCourses()
  fetchTodayTodos()
  fetchAllTodos()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">待办</h2>
    </div>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title-bar">
          <span class="section-title">今日待办</span>
          <div>
            <el-button
              v-if="todayTodos.some((t) => t.status === 'pending')"
              text
              size="small"
              :loading="batchLoading"
              @click="handleBatchComplete"
            >
              全部完成
            </el-button>
            <el-button text size="small" @click="fetchTodayTodos">刷新</el-button>
          </div>
        </div>
      </template>
      <div v-loading="todayLoading">
        <EmptyState
          v-if="!todayLoading && todayTodos.length === 0"
          title="暂无待办事项"
          description="创建学习计划后将自动生成待办"
        />
        <div class="today-grid">
          <div
            v-for="todo in todayTodos"
            :key="todo.id"
            class="today-card"
          >
            <div class="today-card-head">
              <el-tag
                :color="getCourseColor(todo.course_name)"
                effect="dark"
                size="small"
              >
                {{ todo.course_name }}
              </el-tag>
              <el-tag
                v-if="isOverdue(todo)"
                type="danger"
                size="small"
              >
                已逾期
              </el-tag>
              <el-tag
                v-else
                :type="statusTagType[todo.status]"
                size="small"
              >
                {{ statusLabel[todo.status] }}
              </el-tag>
            </div>
            <el-button
              class="today-card-title-link"
              link
              type="primary"
              @click="goToCourse(todo)"
            >
              {{ todo.title }}
            </el-button>
            <div class="today-card-meta">
              <span v-if="todo.scheduled_start">
                {{ formatTime(todo.scheduled_start) }}
                <template v-if="todo.scheduled_end">
                  - {{ formatTime(todo.scheduled_end) }}
                </template>
              </span>
              <span v-else>未安排时间</span>
              <span>预计 {{ todo.estimate_minutes }} 分钟</span>
              <span v-if="todo.actual_minutes !== null">
                实际 {{ todo.actual_minutes }} 分钟
              </span>
            </div>
            <div class="today-card-actions">
              <el-button
                size="small"
                type="success"
                @click="handleComplete(todo)"
              >
                {{ todo.status === 'completed' ? '撤销完成' : '完成' }}
              </el-button>
              <el-button
                size="small"
                @click="handlePostpone(todo)"
              >
                {{ todo.status === 'postponed' ? '恢复' : '暂缓' }}
              </el-button>
              <el-button size="small" @click="openRecordDialog(todo)">
                记录时长
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title">全部待办</div>
      </template>
      <div class="filter-bar">
        <el-date-picker
          v-model="queryDate"
          type="date"
          placeholder="按日期筛选"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          clearable
          style="width: 180px"
          @change="handleFilterChange"
        />
        <el-select
          v-model="query.status"
          placeholder="状态"
          clearable
          style="width: 140px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="opt in statusOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="query.course_id"
          placeholder="课程"
          clearable
          filterable
          :loading="coursesLoading"
          style="width: 200px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="c in courses"
            :key="c.id"
            :label="c.name"
            :value="c.id"
          />
        </el-select>
        <el-button @click="fetchAllTodos">刷新</el-button>
      </div>

      <el-table
        v-loading="allLoading"
        :data="allTodos"
        stripe
        :row-class-name="tableRowClassName"
        empty-text="暂无待办"
        class="todos-table"
      >
        <el-table-column label="标题" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" @click="goToCourse(row)">
              {{ row.title }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" width="140" show-overflow-tooltip />
        <el-table-column prop="scheduled_date" label="日期" width="120" />
        <el-table-column label="时间段" width="160">
          <template #default="{ row }">
            <span v-if="row.scheduled_start">
              {{ formatTime(row.scheduled_start) }}
              <template v-if="row.scheduled_end">
                - {{ formatTime(row.scheduled_end) }}
              </template>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="estimate_minutes" label="预计" width="80" align="center" />
        <el-table-column label="实际" width="80" align="center">
          <template #default="{ row }">
            {{ row.actual_minutes !== null ? row.actual_minutes : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="isOverdue(row)" type="danger" size="small">已逾期</el-tag>
            <el-tag v-else :type="statusTagType[row.status as TodoStatus]" size="small">
              {{ statusLabel[row.status as TodoStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="完成时间" width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.completed_at) || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="success"
              @click="handleComplete(row)"
            >
              {{ row.status === 'completed' ? '撤销' : '完成' }}
            </el-button>
            <el-button
              size="small"
              @click="handlePostpone(row)"
            >
              {{ row.status === 'postponed' ? '恢复' : '暂缓' }}
            </el-button>
            <el-button size="small" @click="openRecordDialog(row)">
              记录
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-loading="allLoading" class="todos-mobile-list">
        <EmptyState
          v-if="!allLoading && allTodos.length === 0"
          title="暂无待办"
          description="调整筛选条件，或先创建一份学习计划"
        />
        <article
          v-for="todo in allTodos"
          :key="todo.id"
          class="todo-mobile-card"
          :class="{ overdue: isOverdue(todo) }"
        >
          <div class="todo-mobile-head">
            <el-tag :color="getCourseColor(todo.course_name)" effect="dark" size="small">
              {{ todo.course_name }}
            </el-tag>
            <el-tag v-if="isOverdue(todo)" type="danger" size="small">已逾期</el-tag>
            <el-tag v-else :type="statusTagType[todo.status]" size="small">
              {{ statusLabel[todo.status] }}
            </el-tag>
          </div>
          <el-button link type="primary" class="todo-mobile-title" @click="goToCourse(todo)">
            {{ todo.title }}
          </el-button>
          <div class="todo-mobile-meta">
            <span>{{ todo.scheduled_date }}</span>
            <span v-if="todo.scheduled_start">
              {{ formatTime(todo.scheduled_start) }}<template v-if="todo.scheduled_end"> - {{ formatTime(todo.scheduled_end) }}</template>
            </span>
            <span>预计 {{ todo.estimate_minutes }} 分钟</span>
            <span v-if="todo.actual_minutes !== null">实际 {{ todo.actual_minutes }} 分钟</span>
          </div>
          <div class="todo-mobile-actions">
            <el-button size="small" type="success" @click="handleComplete(todo)">
              {{ todo.status === 'completed' ? '撤销完成' : '完成' }}
            </el-button>
            <el-button size="small" @click="handlePostpone(todo)">
              {{ todo.status === 'postponed' ? '恢复' : '暂缓' }}
            </el-button>
            <el-button size="small" @click="openRecordDialog(todo)">记录时长</el-button>
          </div>
        </article>
      </div>

      <div v-if="allTotal > 0" class="pagination">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="allTotal"
          :current-page="query.page"
          :page-size="query.page_size"
          :page-sizes="[10, 20, 50]"
          @current-change="handlePageChange"
          @size-change="handlePageSizeChange"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="recordDialogVisible"
      title="记录实际学习时长"
      width="420px"
      @closed="recordTarget = null"
    >
      <div v-if="recordTarget" class="record-info">
        <div class="record-title">{{ recordTarget.title }}</div>
        <div class="record-meta">
          预计 {{ recordTarget.estimate_minutes }} 分钟
        </div>
      </div>
      <el-form label-position="top">
        <el-form-item label="实际学习时长（分钟）">
          <el-input-number
            v-model="recordForm.actual_minutes"
            :min="0"
            :max="1440"
            :step="5"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="recordLoading" @click="handleRecordSubmit">
          保存
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

.today-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.today-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #fafbfc;
}

.today-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.today-card-title,
.today-card-title-link {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}

.today-card-title-link {
  width: fit-content;
  max-width: 100%;
  height: auto;
  padding: 0;
  text-align: left;
  white-space: normal;
}

.today-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}

.today-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.todos-mobile-list {
  display: none;
}

.record-info {
  margin-bottom: 16px;
}

.record-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.record-meta {
  font-size: 13px;
  color: #909399;
}

:deep(.overdue-row) {
  background-color: #fef0f0 !important;
}

:deep(.overdue-row td) {
  border-left: 3px solid #f56c6c;
}

@media (max-width: 768px) {
  .page {
    padding: 16px;
  }

  .section-title-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .today-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .today-card-actions,
  .todo-mobile-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .today-card-actions :deep(.el-button),
  .todo-mobile-actions :deep(.el-button) {
    margin-left: 0;
  }

  .filter-bar {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .filter-bar :deep(.el-date-editor),
  .filter-bar :deep(.el-select),
  .filter-bar :deep(.el-button) {
    width: 100% !important;
    margin-left: 0;
  }

  .todos-table {
    display: none;
  }

  .todos-mobile-list {
    display: grid;
    gap: 12px;
  }

  .todo-mobile-card {
    min-width: 0;
    padding: 14px;
    border: 1px solid var(--border-base);
    border-radius: var(--radius-md);
    background: var(--bg-card);
  }

  .todo-mobile-card.overdue {
    border-left: 4px solid var(--color-danger);
    background: #fff8f7;
  }

  .todo-mobile-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
  }

  .todo-mobile-title {
    width: fit-content;
    max-width: 100%;
    height: auto;
    margin: 10px 0 0;
    padding: 0;
    text-align: left;
    white-space: normal;
  }

  .todo-mobile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    margin-top: 8px;
    color: var(--text-secondary);
    font-size: 12px;
  }

  .todo-mobile-actions {
    margin-top: 12px;
  }

  .pagination {
    justify-content: center;
  }
}
</style>
