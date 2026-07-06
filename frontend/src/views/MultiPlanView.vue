<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type TableInstance } from 'element-plus'
import { listCourses, type Course } from '../api/course'
import {
  createMultiPlan,
  type MultiPlanConstraints,
  type MultiPlanPayload,
  type MultiPlanResult,
  type MultiPlanScheduleItem,
} from '../api/plan'
import type { ApiError } from '../api/auth'

const router = useRouter()

const courses = ref<Course[]>([])
const coursesLoading = ref(false)
const submitting = ref(false)

const tableRef = ref<TableInstance>()

interface CourseConfig {
  deadline: string
  priority: number
}

const courseConfigs = reactive<Record<number, CourseConfig>>({})
const dailyMinutes = ref(120)
const constraints = ref<MultiPlanConstraints>({})

const result = ref<MultiPlanResult | null>(null)
const schedule = ref<MultiPlanScheduleItem[]>([])

function getErrorMessage(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: ApiError | { detail?: string } } }
  const data = e?.response?.data
  if (data) {
    if ('message' in data && data.message) return data.message
    if ('detail' in data && data.detail) return String(data.detail)
  }
  return fallback
}

function toDateString(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function defaultDeadline(): string {
  const d = new Date()
  d.setDate(d.getDate() + 7)
  return toDateString(d)
}

function formatTime(time: string | null): string {
  if (!time) return ''
  return time.length >= 5 ? time.slice(0, 5) : time
}

async function fetchCourses() {
  coursesLoading.value = true
  try {
    const { data } = await listCourses({ page: 1, page_size: 200 })
    courses.value = data.items
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '获取课程列表失败'))
  } finally {
    coursesLoading.value = false
  }
}

function handleSelectionChange(selection: Course[]) {
  const selectedIds = new Set(selection.map((c) => c.id))
  for (const id of Object.keys(courseConfigs)) {
    if (!selectedIds.has(Number(id))) {
      delete courseConfigs[Number(id)]
    }
  }
  for (const c of selection) {
    if (!courseConfigs[c.id]) {
      courseConfigs[c.id] = {
        deadline: defaultDeadline(),
        priority: 3,
      }
    }
  }
}

const selectedCourses = computed<Course[]>(() => {
  return courses.value.filter((c) => !!courseConfigs[c.id])
})

const courseColorMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const c of courses.value) {
    map[c.name] = c.color || '#409eff'
  }
  return map
})

function getCourseColor(name: string): string {
  return courseColorMap.value[name] || '#409eff'
}

const scheduleByDate = computed<Record<string, MultiPlanScheduleItem[]>>(() => {
  const map: Record<string, MultiPlanScheduleItem[]> = {}
  for (const item of schedule.value) {
    if (!map[item.scheduled_date]) map[item.scheduled_date] = []
    map[item.scheduled_date].push(item)
  }
  return map
})

const sortedDates = computed<string[]>(() => {
  return Object.keys(scheduleByDate.value).sort()
})

interface DailyLoad {
  total: number
  byCourse: Record<string, number>
}

const dailyLoadMap = computed<Record<string, DailyLoad>>(() => {
  const map: Record<string, DailyLoad> = {}
  for (const date of sortedDates.value) {
    const byCourse: Record<string, number> = {}
    let total = 0
    for (const item of scheduleByDate.value[date]) {
      byCourse[item.course_name] =
        (byCourse[item.course_name] || 0) + item.estimate_minutes
      total += item.estimate_minutes
    }
    map[date] = { total, byCourse }
  }
  return map
})

const maxDailyTotal = computed<number>(() => {
  let max = 0
  for (const date of sortedDates.value) {
    const t = dailyLoadMap.value[date].total
    if (t > max) max = t
  }
  return Math.max(max, 1)
})

const overloadDays = computed<string[]>(() => {
  return sortedDates.value.filter(
    (date) => dailyLoadMap.value[date].total > dailyMinutes.value,
  )
})

const courseDeadlineMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const c of selectedCourses.value) {
    const cfg = courseConfigs[c.id]
    if (cfg) map[c.name] = cfg.deadline
  }
  return map
})

interface CourseRisk {
  course: string
  lastDate: string
  deadline: string
  scheduledMinutes: number
}

const courseRisks = computed<CourseRisk[]>(() => {
  const risks: CourseRisk[] = []
  const courseLastDate: Record<string, string> = {}
  const courseMinutes: Record<string, number> = {}
  for (const item of schedule.value) {
    const cur = courseLastDate[item.course_name]
    if (!cur || item.scheduled_date > cur) {
      courseLastDate[item.course_name] = item.scheduled_date
    }
    courseMinutes[item.course_name] =
      (courseMinutes[item.course_name] || 0) + item.estimate_minutes
  }
  for (const name of Object.keys(courseLastDate)) {
    const deadline = courseDeadlineMap.value[name]
    if (deadline && courseLastDate[name] > deadline) {
      risks.push({
        course: name,
        lastDate: courseLastDate[name],
        deadline,
        scheduledMinutes: courseMinutes[name] || 0,
      })
    }
  }
  return risks
})

function barWidth(total: number): number {
  return Math.min(100, (total / maxDailyTotal.value) * 100)
}

function segmentWidth(date: string, course: string): number {
  const load = dailyLoadMap.value[date]
  if (!load || load.total === 0) return 0
  return (load.byCourse[course] / load.total) * 100
}

const capacityLeft = computed<number>(() => {
  return Math.min(100, (dailyMinutes.value / maxDailyTotal.value) * 100)
})

const courseListForLegend = computed<string[]>(() => {
  const set = new Set<string>()
  for (const item of schedule.value) set.add(item.course_name)
  return Array.from(set)
})

function validate(): string | null {
  if (selectedCourses.value.length === 0) {
    return '请至少选择一门课程'
  }
  for (const c of selectedCourses.value) {
    const cfg = courseConfigs[c.id]
    if (!cfg || !cfg.deadline) {
      return `请为课程「${c.name}」设置截止日期`
    }
  }
  if (dailyMinutes.value < 10 || dailyMinutes.value > 1440) {
    return '每日可用时间应在 10-1440 分钟之间'
  }
  return null
}

async function handleGenerate() {
  const err = validate()
  if (err) {
    ElMessage.warning(err)
    return
  }
  submitting.value = true
  const payload: MultiPlanPayload = {
    courses: selectedCourses.value.map((c) => {
      const cfg = courseConfigs[c.id]
      return {
        course_id: c.id,
        deadline: cfg.deadline,
        priority: cfg.priority,
      }
    }),
    daily_minutes: dailyMinutes.value,
    constraints: constraints.value,
  }
  try {
    const { data } = await createMultiPlan(payload)
    result.value = data
    schedule.value = data.schedule
    if (data.schedule.length === 0) {
      ElMessage.warning('生成的日程为空，请调整课程或截止日期')
    } else {
      ElMessage.success(`已生成综合计划，共 ${data.schedule.length} 条日程`)
    }
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '生成综合计划失败'))
  } finally {
    submitting.value = false
  }
}

function handleReset() {
  result.value = null
  schedule.value = []
  tableRef.value?.clearSelection()
  for (const id of Object.keys(courseConfigs)) {
    delete courseConfigs[Number(id)]
  }
}

function goBack() {
  router.push('/plans')
}

onMounted(() => {
  fetchCourses()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">多课程综合规划</h2>
      <div class="actions">
        <el-button @click="goBack">返回计划</el-button>
        <el-button v-if="result" @click="handleReset">重新规划</el-button>
      </div>
    </div>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title">选择课程并配置</div>
      </template>
      <el-table
        ref="tableRef"
        :data="courses"
        v-loading="coursesLoading"
        stripe
        empty-text="暂无课程"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column label="课程" min-width="180">
          <template #default="{ row }">
            <div class="course-cell">
              <span
                class="color-dot"
                :style="{ backgroundColor: row.color || '#409eff' }"
              />
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="teacher" label="教师" width="140" show-overflow-tooltip />
        <el-table-column prop="semester" label="学期" width="140" show-overflow-tooltip />
        <el-table-column prop="description" label="简介" min-width="200" show-overflow-tooltip />
      </el-table>

      <div v-if="selectedCourses.length > 0" class="config-area">
        <div class="config-title">已选课程配置</div>
        <el-table :data="selectedCourses" border size="small">
          <el-table-column label="课程" min-width="160">
            <template #default="{ row }">
              <div class="course-cell">
                <span
                  class="color-dot"
                  :style="{ backgroundColor: row.color || '#409eff' }"
                />
                <span>{{ row.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="截止日期" width="200">
            <template #default="{ row }">
              <el-date-picker
                v-model="courseConfigs[row.id].deadline"
                type="date"
                placeholder="选择截止日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                style="width: 100%"
                size="small"
              />
            </template>
          </el-table-column>
          <el-table-column label="优先级（1-5）" width="180">
            <template #default="{ row }">
              <el-input-number
                v-model="courseConfigs[row.id].priority"
                :min="1"
                :max="5"
                :step="1"
                size="small"
                controls-position="right"
              />
            </template>
          </el-table-column>
        </el-table>

        <div class="constraint-area">
          <div class="config-title">约束设置</div>
          <el-row :gutter="16">
            <el-col :span="12">
              <div class="field-label">每日可用时间（分钟）</div>
              <el-input-number
                v-model="dailyMinutes"
                :min="10"
                :max="1440"
                :step="10"
                style="width: 100%"
              />
            </el-col>
          </el-row>
        </div>

        <div class="submit-area">
          <el-button
            type="primary"
            size="large"
            :loading="submitting"
            @click="handleGenerate"
          >
            生成综合计划
          </el-button>
        </div>
      </div>
      <el-empty
        v-else
        description="请在上方表格中勾选需要规划的课程"
        :image-size="80"
      />
    </el-card>

    <template v-if="result">
      <el-card v-if="schedule.length === 0" class="section-card" shadow="never">
        <el-empty description="生成的日程为空，请调整课程或截止日期后重试" />
      </el-card>

      <template v-else>
        <el-card
          v-if="overloadDays.length > 0 || courseRisks.length > 0"
          class="section-card risk-card"
          shadow="never"
        >
          <template #header>
            <div class="section-title risk-title">风险提示</div>
          </template>
          <el-alert
            v-if="overloadDays.length > 0"
            type="warning"
            show-icon
            :closable="false"
            class="risk-alert"
          >
            <template #title>
              以下日期任务负载超过每日可用时间（{{ dailyMinutes }} 分钟）：
              {{ overloadDays.join('、') }}
            </template>
          </el-alert>
          <el-alert
            v-for="r in courseRisks"
            :key="r.course"
            type="error"
            show-icon
            :closable="false"
            class="risk-alert"
          >
            <template #title>
              课程「{{ r.course }}」日程延伸至 {{ r.lastDate }}，已超过截止日期
              {{ r.deadline }}，累计安排 {{ r.scheduledMinutes }} 分钟
            </template>
          </el-alert>
        </el-card>

        <el-card class="section-card" shadow="never">
          <template #header>
            <div class="section-title-bar">
              <span class="section-title">多课程负载图</span>
              <span class="section-tip">
                每日容量 {{ dailyMinutes }} 分钟 · 柱状宽度按最大日负载缩放
              </span>
            </div>
          </template>
          <div v-if="courseListForLegend.length > 0" class="legend">
            <div
              v-for="name in courseListForLegend"
              :key="name"
              class="legend-item"
            >
              <span
                class="legend-dot"
                :style="{ backgroundColor: getCourseColor(name) }"
              />
              <span class="legend-text">{{ name }}</span>
            </div>
          </div>
          <div class="load-chart">
            <div class="load-header">
              <div class="load-date-col">日期</div>
              <div class="load-bar-col">
                <div class="load-track">
                  <div
                    class="capacity-line"
                    :style="{ left: capacityLeft + '%' }"
                  >
                    <span class="capacity-label">容量</span>
                  </div>
                </div>
              </div>
              <div class="load-total-col">合计</div>
            </div>
            <div
              v-for="date in sortedDates"
              :key="date"
              class="load-row"
            >
              <div class="load-date-col">{{ date }}</div>
              <div class="load-bar-col">
                <div class="load-track">
                  <div
                    class="load-bar"
                    :style="{ width: barWidth(dailyLoadMap[date].total) + '%' }"
                    :class="{ overload: dailyLoadMap[date].total > dailyMinutes }"
                  >
                    <div
                      v-for="course in Object.keys(dailyLoadMap[date].byCourse)"
                      :key="course"
                      class="load-segment"
                      :style="{
                        width: segmentWidth(date, course) + '%',
                        backgroundColor: getCourseColor(course),
                      }"
                      :title="`${course}: ${dailyLoadMap[date].byCourse[course]} 分钟`"
                    >
                      <span v-if="segmentWidth(date, course) > 15" class="seg-text">
                        {{ dailyLoadMap[date].byCourse[course] }}
                      </span>
                    </div>
                  </div>
                  <div
                    class="capacity-line"
                    :style="{ left: capacityLeft + '%' }"
                  />
                </div>
              </div>
              <div
                class="load-total-col"
                :class="{ 'total-overload': dailyLoadMap[date].total > dailyMinutes }"
              >
                {{ dailyLoadMap[date].total }} 分钟
              </div>
            </div>
          </div>
        </el-card>

        <el-card class="section-card" shadow="never">
          <template #header>
            <div class="section-title">综合日程</div>
          </template>
          <el-table :data="schedule" stripe empty-text="暂无日程">
            <el-table-column prop="scheduled_date" label="日期" width="130" />
            <el-table-column label="课程" min-width="150">
              <template #default="{ row }">
                <span
                  class="course-tag"
                  :style="{
                    backgroundColor: getCourseColor(row.course_name),
                  }"
                >
                  {{ row.course_name }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="任务标题" min-width="200" show-overflow-tooltip />
            <el-table-column label="时间段" width="180">
              <template #default="{ row }">
                <span v-if="row.start_time">
                  {{ formatTime(row.start_time) }}
                  <template v-if="row.end_time"> - {{ formatTime(row.end_time) }}</template>
                </span>
                <span v-else class="text-muted">未安排</span>
              </template>
            </el-table-column>
            <el-table-column prop="estimate_minutes" label="预计分钟" width="110" align="center" />
          </el-table>
        </el-card>

        <el-card class="section-card" shadow="never">
          <template #header>
            <div class="section-title">按日期分组</div>
          </template>
          <div v-for="date in sortedDates" :key="date" class="date-group">
            <div class="date-header">
              <span class="date-text">{{ date }}</span>
              <span class="date-count">
                {{ scheduleByDate[date].length }} 条 ·
                {{ dailyLoadMap[date].total }} 分钟
              </span>
            </div>
            <div class="todo-list">
              <div
                v-for="(item, idx) in scheduleByDate[date]"
                :key="date + '-' + idx"
                class="todo-item"
              >
                <div class="todo-main">
                  <span
                    class="course-tag"
                    :style="{ backgroundColor: getCourseColor(item.course_name) }"
                  >
                    {{ item.course_name }}
                  </span>
                  <span class="todo-title">{{ item.title }}</span>
                </div>
                <div class="todo-meta">
                  <span v-if="item.start_time">
                    {{ formatTime(item.start_time) }}
                    <template v-if="item.end_time"> - {{ formatTime(item.end_time) }}</template>
                  </span>
                  <span>{{ item.estimate_minutes }} 分钟</span>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </template>
    </template>

    <el-empty
      v-else
      description="选择多门课程并配置截止日期，生成跨课程综合学习计划"
    />
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

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
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

.course-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.config-area {
  margin-top: 20px;
}

.config-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.constraint-area {
  margin-top: 20px;
}

.field-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}

.submit-area {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.risk-card {
  border: 1px solid #f56c6c;
}

.risk-title {
  color: #f56c6c;
}

.risk-alert {
  margin-bottom: 10px;
}

.risk-alert:last-child {
  margin-bottom: 0;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.legend-text {
  font-size: 13px;
  color: #606266;
}

.load-chart {
  display: flex;
  flex-direction: column;
}

.load-header {
  display: flex;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
  font-size: 12px;
  color: #909399;
}

.load-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
}

.load-date-col {
  width: 110px;
  flex-shrink: 0;
  font-size: 13px;
  color: #303133;
}

.load-bar-col {
  flex: 1;
  min-width: 0;
  padding: 0 12px;
}

.load-total-col {
  width: 100px;
  flex-shrink: 0;
  text-align: right;
  font-size: 13px;
  color: #606266;
}

.total-overload {
  color: #f56c6c;
  font-weight: 600;
}

.load-track {
  position: relative;
  height: 24px;
  background: #f5f7fa;
  border-radius: 4px;
  overflow: visible;
}

.load-bar {
  height: 100%;
  display: flex;
  border-radius: 4px;
  overflow: hidden;
  min-width: 2px;
  transition: width 0.3s;
}

.load-bar.overload {
  box-shadow: 0 0 0 1px #f56c6c;
}

.load-segment {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.seg-text {
  font-size: 11px;
  color: #fff;
  font-weight: 600;
  white-space: nowrap;
}

.capacity-line {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: #e6a23c;
  z-index: 2;
  pointer-events: none;
}

.capacity-label {
  position: absolute;
  top: -16px;
  left: 4px;
  font-size: 10px;
  color: #e6a23c;
  white-space: nowrap;
}

.load-header .capacity-line {
  top: 0;
  bottom: 0;
}

.course-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #fff;
  white-space: nowrap;
}

.date-group {
  margin-bottom: 16px;
}

.date-group:last-child {
  margin-bottom: 0;
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
  gap: 10px;
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

.todo-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}

.text-muted {
  color: #c0c4cc;
}
</style>
