<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCourses, type Course } from '../api/course'
import { MAX_PAGE_SIZE } from '../constants/pagination'
import { listKnowledgePoints, type KnowledgePoint } from '../api/knowledge'
import {
  createQuiz,
  deleteQuiz,
  getQuizzes,
  getQuiz,
  getQuizResult,
  submitQuiz,
  getWeakPoints,
  type Quiz,
  type QuizResult,
  type QuizResultItem,
  type QuizStatus,
  type WeakPoint,
} from '../api/quiz'
import { parseApiError } from '../utils/error'
import EmptyState from '../components/common/EmptyState.vue'
import QuizAnswerControl from '../components/quiz/QuizAnswerControl.vue'

const route = useRoute()

const courses = ref<Course[]>([])
const coursesLoading = ref(false)
const selectedCourseId = ref<number | undefined>(undefined)

const quizzes = ref<Quiz[]>([])
const quizzesLoading = ref(false)

const weakPoints = ref<WeakPoint[]>([])
const weakPointsLoading = ref(false)

const dialogVisible = ref(false)
const dialogLoading = ref(false)
const knowledgePoints = ref<KnowledgePoint[]>([])
const knowledgePointsLoading = ref(false)
const genForm = reactive({
  question_count: 5,
  knowledge_point_ids: [] as number[],
})

const activeQuiz = ref<Quiz | null>(null)
const activeQuizLoading = ref(false)
const answers = ref<Record<number, string | string[]>>({})
const submitting = ref(false)
const quizResult = ref<QuizResult | null>(null)
const deletingQuizId = ref<number | null>(null)

// Index of the question currently displayed while answering (one
// question at a time). Reset to 0 when a quiz starts.
const currentIndex = ref(0)

const currentQuestion = computed(() => {
  if (!activeQuiz.value) return null
  return activeQuiz.value.items[currentIndex.value] ?? null
})

/**
 * A quiz is considered "in progress" (and thus worth confirming before
 * leaving) only while the user is still answering — i.e. the quiz is
 * open AND no result has been produced yet.
 */
const quizInProgress = computed(
  () => activeQuiz.value?.status === 'draft' && quizResult.value === null,
)

function isAnswered(itemId: number): boolean {
  const ans = answers.value[itemId]
  return ans !== undefined && ans !== '' && (!Array.isArray(ans) || ans.length > 0)
}

const answeredCount = computed(() => {
  if (!activeQuiz.value) return 0
  return activeQuiz.value.items.filter((it) => isAnswered(it.id)).length
})

const progressPercentage = computed(() => {
  if (!activeQuiz.value || activeQuiz.value.items.length === 0) return 0
  return Math.round(
    (answeredCount.value / activeQuiz.value.items.length) * 100,
  )
})

const resultMap = computed<Record<number, QuizResultItem>>(() => {
  const map: Record<number, QuizResultItem> = {}
  if (quizResult.value) {
    for (const r of quizResult.value.items) {
      map[r.id] = r
    }
  }
  return map
})

const statusLabel: Record<QuizStatus, string> = {
  draft: '待作答',
  submitted: '已提交',
}

const statusTagType: Record<QuizStatus, 'warning' | 'success'> = {
  draft: 'warning',
  submitted: 'success',
}

function formatQuizStatus(status: string): string {
  return statusLabel[status as QuizStatus] ?? '状态未知'
}

function quizStatusTagType(status: string): 'info' | 'warning' | 'success' {
  return statusTagType[status as QuizStatus] ?? 'info'
}

function quizActionLabel(status: string): string {
  if (status === 'submitted') return '查看结果'
  if (status === 'draft') return '开始答题'
  return '暂不可用'
}

function isQuizOpenable(status: string): status is QuizStatus {
  return status === 'draft' || status === 'submitted'
}

function questionTypeLabel(t: string): string {
  const map: Record<string, string> = {
    choice: '选择题',
    true_false: '判断题',
    short_answer: '简答题',
  }
  return map[t] || t
}

function formatDateTime(dt: string | null): string {
  if (!dt) return ''
  return dt.replace('T', ' ').slice(0, 19)
}

function weakPointLevel(wrongCount: number): 'info' | 'warning' | 'danger' {
  if (wrongCount >= 5) return 'danger'
  if (wrongCount >= 2) return 'warning'
  return 'info'
}

function weakPointLabel(wrongCount: number): string {
  if (wrongCount >= 5) return '严重'
  if (wrongCount >= 2) return '一般'
  return '轻微'
}

async function fetchCourses() {
  coursesLoading.value = true
  try {
    const { data } = await listCourses({ page: 1, page_size: MAX_PAGE_SIZE })
    courses.value = data.items
    if (courses.value.length > 0 && selectedCourseId.value === undefined) {
      const requestedCourseId = Number(route.query.course_id)
      selectedCourseId.value = courses.value.some((course) => course.id === requestedCourseId)
        ? requestedCourseId
        : courses.value[0].id
      fetchQuizzes()
      fetchWeakPoints()
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取课程列表失败'))
  } finally {
    coursesLoading.value = false
  }
}

async function fetchQuizzes() {
  if (selectedCourseId.value === undefined) {
    quizzes.value = []
    return
  }
  quizzesLoading.value = true
  try {
    const { data } = await getQuizzes(selectedCourseId.value)
    quizzes.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取测验列表失败'))
  } finally {
    quizzesLoading.value = false
  }
}

async function fetchWeakPoints() {
  if (selectedCourseId.value === undefined) {
    weakPoints.value = []
    return
  }
  weakPointsLoading.value = true
  try {
    const { data } = await getWeakPoints(selectedCourseId.value)
    weakPoints.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取薄弱点失败'))
  } finally {
    weakPointsLoading.value = false
  }
}

async function fetchKnowledgePoints() {
  if (selectedCourseId.value === undefined) return
  knowledgePointsLoading.value = true
  try {
    const { data } = await listKnowledgePoints(selectedCourseId.value)
    knowledgePoints.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取知识点列表失败'))
  } finally {
    knowledgePointsLoading.value = false
  }
}

function handleCourseChange() {
  activeQuiz.value = null
  quizResult.value = null
  answers.value = {}
  fetchQuizzes()
  fetchWeakPoints()
}

function openGenerateDialog() {
  if (selectedCourseId.value === undefined) {
    ElMessage.warning('请先选择课程')
    return
  }
  genForm.question_count = 5
  genForm.knowledge_point_ids = []
  dialogVisible.value = true
  fetchKnowledgePoints()
}

async function handleGenerate() {
  if (selectedCourseId.value === undefined) return
  dialogLoading.value = true
  try {
    const { data } = await createQuiz(
      selectedCourseId.value,
      genForm.knowledge_point_ids.length > 0 ? genForm.knowledge_point_ids : undefined,
      genForm.question_count,
    )
    dialogVisible.value = false
    ElMessage.success('测验已生成')
    fetchQuizzes()
    openQuiz(data)
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成测验失败'))
  } finally {
    dialogLoading.value = false
  }
}

async function openQuiz(quiz: Quiz) {
  activeQuizLoading.value = true
  try {
    const { data } = await getQuiz(quiz.id)
    if (!isQuizOpenable(data.status)) {
      ElMessage.error('测验状态异常，请刷新后重试')
      return
    }

    if (data.status === 'submitted') {
      const { data: result } = await getQuizResult(data.id)
      activeQuiz.value = data
      quizResult.value = result
      answers.value = Object.fromEntries(
        result.items.map((item) => [item.id, item.user_answer ?? '']),
      )
    } else {
      activeQuiz.value = data
      answers.value = Object.fromEntries(data.items.map((item) => [item.id, item.question_type === 'multiple_choice' ? [] : '']))
      quizResult.value = null
    }
    currentIndex.value = 0
  } catch (err) {
    ElMessage.error(parseApiError(err, '加载测验详情失败'))
  } finally {
    activeQuizLoading.value = false
  }
}

function resetQuizState() {
  activeQuiz.value = null
  quizResult.value = null
  answers.value = {}
  currentIndex.value = 0
}

const EXIT_CONFIRM_MESSAGE =
  '测验尚未完成，确定要退出吗？退出后答题进度将丢失。'

/**
 * Ask the user to confirm leaving an in-progress quiz. Resolves to
 * ``true`` when it is safe to leave (either the quiz is not in progress
 * or the user confirmed), ``false`` when the user cancelled.
 */
async function confirmLeave(): Promise<boolean> {
  if (!quizInProgress.value) return true
  try {
    await ElMessageBox.confirm(EXIT_CONFIRM_MESSAGE, '提示', {
      confirmButtonText: '确定退出',
      cancelButtonText: '继续答题',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

async function confirmExitQuiz() {
  const ok = await confirmLeave()
  if (!ok) return
  resetQuizState()
}

async function handleSubmit() {
  if (!activeQuiz.value) return
  const unanswered = activeQuiz.value.items.filter((item) => {
    const ans = answers.value[item.id]
    return ans === undefined || ans === '' || (Array.isArray(ans) && ans.length === 0)
  })
  if (unanswered.length > 0) {
    ElMessage.warning(`还有 ${unanswered.length} 道题未作答`)
    return
  }
  submitting.value = true
  try {
    const payload = activeQuiz.value.items.map((item) => ({
      item_id: item.id,
      user_answer: answers.value[item.id] ?? '',
    }))
    const { data } = await submitQuiz(activeQuiz.value.id, payload)
    quizResult.value = data
    activeQuiz.value = {
      ...activeQuiz.value,
      status: 'submitted',
      score: data.score,
    }
    ElMessage.success('提交成功')
    fetchQuizzes()
    fetchWeakPoints()
  } catch (err) {
    ElMessage.error(parseApiError(err, '提交测验失败'))
  } finally {
    submitting.value = false
  }
}

async function handleDeleteQuiz(quiz: Quiz) {
  try {
    await ElMessageBox.confirm(
      `确定要删除测验「${quiz.title}」吗？删除后不可恢复。`,
      '删除测验',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  deletingQuizId.value = quiz.id
  try {
    await deleteQuiz(quiz.id)
    ElMessage.success('测验已删除')
    // If the user is deleting the quiz currently open for review, close
    // it so we never render stale state.
    if (activeQuiz.value?.id === quiz.id) {
      resetQuizState()
    }
    fetchQuizzes()
    fetchWeakPoints()
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除测验失败'))
  } finally {
    deletingQuizId.value = null
  }
}

function goToQuestion(idx: number) {
  if (!activeQuiz.value) return
  if (idx < 0 || idx >= activeQuiz.value.items.length) return
  currentIndex.value = idx
}

function goPrev() {
  goToQuestion(currentIndex.value - 1)
}

function goNext() {
  goToQuestion(currentIndex.value + 1)
}

/**
 * Keyboard shortcuts during quiz answering:
 * - true_false: Y/T = true, N/F = false
 * - choice: number keys 1-9 select the corresponding option
 * - Enter: submit the quiz (only when the current question is answered)
 */
function handleKeydown(e: KeyboardEvent) {
  if (!quizInProgress.value || !currentQuestion.value) return

  const q = currentQuestion.value
  const key = e.key.toLowerCase()

  if (q.question_type === 'true_false') {
    if (key === 'y' || key === 't') {
      answers.value[q.id] = 'true'
    } else if (key === 'n' || key === 'f') {
      answers.value[q.id] = 'false'
    }
  } else if (q.question_type === 'choice') {
    const num = parseInt(e.key)
    if (num >= 1 && num <= (q.options?.length || 0)) {
      answers.value[q.id] = q.options[num - 1].value
    }
  }

  if (e.key === 'Enter' && answers.value[q.id]) {
    handleSubmit()
  }
}

// Guard route-level navigation (clicking another menu item, back button,
// etc.) while a quiz is in progress. The guard is async-aware and
// cancels the navigation when the user declines the prompt.
onBeforeRouteLeave(async () => {
  const ok = await confirmLeave()
  if (!ok) return false
  resetQuizState()
  return true
})

// Guard browser refresh / close. beforeunload cannot show a custom
// dialog, so we set returnValue to trigger the browser's native prompt.
function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!quizInProgress.value) return
  event.preventDefault()
  event.returnValue = EXIT_CONFIRM_MESSAGE
  return EXIT_CONFIRM_MESSAGE
}

onMounted(() => {
  fetchCourses()
  window.addEventListener('beforeunload', handleBeforeUnload)
})

// Attach the keyboard-shortcut listener only while a quiz is actively
// being answered (not during result review or list browsing).
watch(quizInProgress, (val) => {
  if (val) {
    window.addEventListener('keydown', handleKeydown)
  } else {
    window.removeEventListener('keydown', handleKeydown)
  }
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">测验</h2>
      <div class="toolbar-actions">
        <el-select
          v-model="selectedCourseId"
          class="course-select"
          placeholder="请选择课程"
          :loading="coursesLoading"
          @change="handleCourseChange"
        >
          <el-option
            v-for="c in courses"
            :key="c.id"
            :label="c.name"
            :value="c.id"
          />
        </el-select>
        <el-button
          class="generate-button"
          type="primary"
          :disabled="selectedCourseId === undefined"
          @click="openGenerateDialog"
        >
          生成测验
        </el-button>
      </div>
    </div>

    <div v-if="activeQuiz" v-loading="activeQuizLoading" class="quiz-active">
      <div class="quiz-active-header">
        <el-button @click="confirmExitQuiz">返回列表</el-button>
        <div class="quiz-active-title">{{ activeQuiz.title }}</div>
      </div>

      <!-- Result phase: score + all questions with correct answers -->
      <template v-if="quizResult">
        <el-alert
          :title="`得分：${quizResult.score} / ${quizResult.total}`"
          :type="quizResult.score === quizResult.total ? 'success' : 'warning'"
          :closable="false"
          show-icon
          class="result-alert"
        />

        <el-card
          v-for="(item, idx) in activeQuiz.items"
          :key="item.id"
          class="question-card"
          shadow="never"
        >
          <template #header>
            <div class="question-header">
              <span class="question-index">第 {{ idx + 1 }} 题</span>
              <el-tag size="small" type="info">
                {{ questionTypeLabel(item.question_type) }}
              </el-tag>
              <el-tag
                v-if="resultMap[item.id]"
                :type="resultMap[item.id].is_correct ? 'success' : 'danger'"
                size="small"
              >
                {{ resultMap[item.id].is_correct ? '正确' : '错误' }}
              </el-tag>
            </div>
          </template>
          <div class="question-text">{{ item.question_text }}</div>

          <div class="question-result">
            <div
              class="result-row"
              :class="
                resultMap[item.id]?.is_correct
                  ? 'result-user-correct'
                  : 'result-user-wrong'
              "
            >
              <span class="result-label">你的答案：</span>
              <span class="result-value">
                {{ resultMap[item.id]?.user_answer || '（未作答）' }}
              </span>
            </div>
            <div class="result-row result-correct-answer">
              <span class="result-label">正确答案：</span>
              <span class="result-value result-correct-value">
                {{ resultMap[item.id]?.correct_answer || '无' }}
              </span>
            </div>
            <div class="result-row">
              <span class="result-label">解析：</span>
              <span class="result-value">
                {{ resultMap[item.id]?.explanation || '无' }}
              </span>
            </div>
            <div v-if="resultMap[item.id]?.rubric_feedback?.length" class="rubric-feedback">
              <span class="result-label">评分要点：</span>
              <el-tag
                v-for="feedback in resultMap[item.id].rubric_feedback"
                :key="feedback.criterion"
                :type="feedback.met ? 'success' : 'warning'"
                size="small"
                class="rubric-tag"
              >
                {{ feedback.criterion }}：{{ feedback.message }}
              </el-tag>
              <el-alert
                v-if="resultMap[item.id].needs_review"
                title="该答案接近自动评分边界，建议教师或助教复核。"
                type="info"
                :closable="false"
                show-icon
                class="rubric-review-alert"
              />
            </div>
          </div>
        </el-card>
      </template>

      <!-- Answering phase: progress indicator + one question at a time -->
      <template v-else-if="activeQuiz.items.length > 0">
        <div class="quiz-progress">
          <div class="progress-info">
            <span class="progress-text">
              第 {{ currentIndex + 1 }} / {{ activeQuiz.items.length }} 题
            </span>
            <span class="progress-answered">
              已答 {{ answeredCount }} / {{ activeQuiz.items.length }}
            </span>
          </div>
          <el-progress
            :percentage="progressPercentage"
            :stroke-width="8"
            :show-text="false"
          />
          <div class="question-nav">
            <button
              v-for="(item, idx) in activeQuiz.items"
              :key="item.id"
              type="button"
              class="qnav-btn"
              :class="{
                'qnav-answered': isAnswered(item.id),
                'qnav-current': idx === currentIndex,
              }"
              :title="`第 ${idx + 1} 题`"
              @click="goToQuestion(idx)"
            >
              {{ idx + 1 }}
            </button>
          </div>
        </div>

        <el-card
          v-if="currentQuestion"
          class="question-card"
          shadow="never"
        >
          <template #header>
            <div class="question-header">
              <span class="question-index">
                第 {{ currentIndex + 1 }} 题
              </span>
              <el-tag size="small" type="info">
                {{ questionTypeLabel(currentQuestion.question_type) }}
              </el-tag>
            </div>
          </template>
          <div class="question-text">{{ currentQuestion.question_text }}</div>

          <div class="question-answer">
            <QuizAnswerControl
              :item="currentQuestion"
              :model-value="answers[currentQuestion.id]"
              @update:model-value="answers[currentQuestion.id] = $event"
            />
          </div>
        </el-card>

        <div
          v-if="currentQuestion && currentQuestion.question_type !== 'short_answer'"
          class="keyboard-hint"
        >
          <el-text type="info" size="small">
            键盘快捷键：数字键选择选项，Enter 提交答案
          </el-text>
        </div>

        <div class="quiz-actions">
          <el-button :disabled="currentIndex === 0" @click="goPrev">
            上一题
          </el-button>
          <el-button
            v-if="currentIndex < activeQuiz.items.length - 1"
            type="primary"
            @click="goNext"
          >
            下一题
          </el-button>
          <el-button
            type="primary"
            :loading="submitting"
            @click="handleSubmit"
          >
            提交测验
          </el-button>
        </div>
      </template>
    </div>

    <template v-else>
      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-title">测验列表</div>
        </template>
        <EmptyState
          v-if="!quizzesLoading && quizzes.length === 0"
          title="还没有测验"
          description="生成测验来检验学习效果"
        />
        <div
          v-else
          v-loading="quizzesLoading"
          class="quiz-list-shell"
        >
          <el-table
            class="quiz-table"
            :data="quizzes"
            stripe
            empty-text="暂无测验"
          >
            <el-table-column
              prop="title"
              label="标题"
              min-width="180"
              show-overflow-tooltip
            />
            <el-table-column
              prop="question_count"
              label="题数"
              width="80"
              align="center"
            />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="quizStatusTagType(row.status)" size="small">
                  {{ formatQuizStatus(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="得分" width="100" align="center">
              <template #default="{ row }">
                <span v-if="row.score !== null && row.score !== undefined">
                  {{ row.score }} / {{ row.question_count }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="180" align="center">
              <template #default="{ row }">
                {{ formatDateTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="210" align="center" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  :disabled="!isQuizOpenable(row.status)"
                  @click="openQuiz(row)"
                >
                  {{ quizActionLabel(row.status) }}
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  :loading="deletingQuizId === row.id"
                  @click="handleDeleteQuiz(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="quiz-card-list" role="list" aria-label="测验列表">
            <article
              v-for="quiz in quizzes"
              :key="quiz.id"
              class="quiz-list-card"
              role="listitem"
            >
              <div class="quiz-card-header">
                <h3 class="quiz-card-title">{{ quiz.title }}</h3>
                <el-tag :type="quizStatusTagType(quiz.status)" size="small">
                  {{ formatQuizStatus(quiz.status) }}
                </el-tag>
              </div>
              <dl class="quiz-card-meta">
                <div>
                  <dt>题目数量</dt>
                  <dd>{{ quiz.question_count }} 题</dd>
                </div>
                <div>
                  <dt>得分</dt>
                  <dd>
                    <template v-if="quiz.score !== null">
                      {{ quiz.score }} / {{ quiz.question_count }}
                    </template>
                    <template v-else>尚未提交</template>
                  </dd>
                </div>
                <div class="quiz-card-created">
                  <dt>创建时间</dt>
                  <dd>{{ formatDateTime(quiz.created_at) }}</dd>
                </div>
              </dl>
              <div class="quiz-card-actions">
                <el-button
                  type="primary"
                  :disabled="!isQuizOpenable(quiz.status)"
                  @click="openQuiz(quiz)"
                >
                  {{ quizActionLabel(quiz.status) }}
                </el-button>
                <el-button
                  type="danger"
                  plain
                  :loading="deletingQuizId === quiz.id"
                  @click="handleDeleteQuiz(quiz)"
                >
                  删除
                </el-button>
              </div>
            </article>
          </div>
        </div>
      </el-card>

      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-title">薄弱知识点</div>
        </template>
        <div v-loading="weakPointsLoading">
          <div
            v-if="!weakPointsLoading && weakPoints.length === 0"
            class="empty-weak-points"
          >
            暂无薄弱知识点数据
          </div>
          <div class="weak-points">
            <div
              v-for="wp in weakPoints"
              :key="wp.id"
              class="weak-point-item"
            >
              <div class="weak-point-main">
                <div class="weak-point-title">{{ wp.knowledge_point_title }}</div>
                <div class="weak-point-meta">
                  <span>错误次数：{{ wp.wrong_count }}</span>
                  <span v-if="wp.last_wrong_at">
                    最近错误：{{ formatDateTime(wp.last_wrong_at) }}
                  </span>
                </div>
              </div>
              <el-tag :type="weakPointLevel(wp.wrong_count)" size="small">
                {{ weakPointLabel(wp.wrong_count) }}
              </el-tag>
            </div>
          </div>
        </div>
      </el-card>
    </template>

    <el-dialog
      v-model="dialogVisible"
      title="生成测验"
      width="min(520px, calc(100vw - 32px))"
    >
      <el-form label-position="top" v-loading="knowledgePointsLoading">
        <el-form-item label="题目数量">
          <el-input-number
            v-model="genForm.question_count"
            :min="1"
            :max="20"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="知识点范围（可选，不选则覆盖全部）">
          <el-select
            v-model="genForm.knowledge_point_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="不选则覆盖全部知识点"
            style="width: 100%"
          >
            <el-option
              v-for="kp in knowledgePoints"
              :key="kp.id"
              :label="kp.title"
              :value="Number(kp.id)"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogLoading" @click="handleGenerate">
          生成
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

.course-select {
  width: 240px;
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

.quiz-card-list {
  display: none;
}

.quiz-active {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.quiz-active-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.quiz-active-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.result-alert {
  margin-bottom: 4px;
}

.question-card {
  margin-bottom: 4px;
}

.question-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.question-index {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.question-text {
  font-size: 15px;
  color: #303133;
  line-height: 1.6;
  margin-bottom: 12px;
}

.question-answer {
  margin-top: 4px;
}

.answer-radio-group {
  display: flex;
  flex-direction: column;
}

.answer-option {
  margin-bottom: 8px;
}

.question-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
}

.result-row {
  font-size: 14px;
  color: #303133;
  line-height: 1.6;
}

.result-label {
  font-weight: 600;
  color: #606266;
}

.result-value {
  color: #303133;
}

/* Correct / wrong answer coloring in the result review. */
.result-user-correct .result-value {
  color: #67c23a;
  font-weight: 600;
}

.result-user-wrong .result-value {
  color: #f56c6c;
  font-weight: 600;
  text-decoration: line-through;
}

.result-correct-answer {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 4px;
  padding: 6px 10px;
}

.result-correct-answer .result-label {
  color: #67c23a;
}

.result-correct-value {
  color: #67c23a;
  font-weight: 600;
}

.quiz-actions {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
}

/* Answer progress indicator (progress bar + question number buttons). */
.quiz-progress {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  background: #f5f7fa;
  border-radius: 6px;
}

.progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  color: #303133;
}

.progress-text {
  font-weight: 600;
}

.progress-answered {
  color: #909399;
  font-size: 13px;
}

.question-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.qnav-btn {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
  color: #606266;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.qnav-btn:hover {
  border-color: #409eff;
  color: #409eff;
}

/* Answered questions get a green dot / green tint. */
.qnav-answered {
  border-color: #67c23a;
  color: #67c23a;
  background: #f0f9eb;
}

.qnav-answered::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #67c23a;
  margin-right: 6px;
}

/* The currently displayed question is highlighted. */
.qnav-current {
  border-color: #409eff;
  color: #fff;
  background: #409eff;
}

.qnav-current::before {
  background: #fff;
}

.empty-weak-points {
  text-align: center;
  color: #909399;
  padding: 40px 0;
  font-size: 14px;
}

.weak-points {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 60px;
}

.weak-point-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.weak-point-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.weak-point-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  overflow-wrap: anywhere;
}

.rubric-feedback {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}

.rubric-tag {
  white-space: normal;
  height: auto;
  line-height: 1.5;
}

.rubric-review-alert {
  width: 100%;
  margin-top: 2px;
}

.weak-point-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #909399;
}

.keyboard-hint {
  text-align: center;
  margin: 8px 0;
}

@media (max-width: 768px) {
  .page {
    padding: 16px;
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
    gap: 14px;
  }

  .toolbar-actions {
    align-items: stretch;
    flex-direction: column;
    width: 100%;
  }

  .course-select,
  .generate-button {
    width: 100%;
  }

  .section-card :deep(.el-card__header),
  .section-card :deep(.el-card__body),
  .question-card :deep(.el-card__header),
  .question-card :deep(.el-card__body) {
    padding: 14px;
  }

  .quiz-table {
    display: none;
  }

  .quiz-card-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .quiz-list-card {
    padding: 14px;
    border: 1px solid #e4e7ed;
    border-radius: 8px;
    background: #fff;
  }

  .quiz-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .quiz-card-header :deep(.el-tag) {
    flex: 0 0 auto;
  }

  .quiz-card-title {
    min-width: 0;
    margin: 0;
    color: #303133;
    font-size: 15px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .quiz-card-meta {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin: 14px 0;
  }

  .quiz-card-meta > div {
    min-width: 0;
  }

  .quiz-card-meta dt {
    margin-bottom: 3px;
    color: #909399;
    font-size: 12px;
  }

  .quiz-card-meta dd {
    margin: 0;
    color: #303133;
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .quiz-card-created {
    grid-column: 1 / -1;
  }

  .quiz-card-actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 10px;
  }

  .quiz-card-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .weak-point-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .weak-point-meta {
    flex-direction: column;
    gap: 4px;
    line-height: 1.5;
  }

  .weak-point-item :deep(.el-tag) {
    align-self: flex-start;
  }

  .quiz-active-header {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 10px;
  }

  .quiz-active-title {
    min-width: 0;
    flex: 1 1 180px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .question-header,
  .progress-info {
    flex-wrap: wrap;
  }

  .answer-option {
    height: auto;
    align-items: flex-start;
    white-space: normal;
  }

  .answer-option :deep(.el-radio__label) {
    padding-right: 4px;
    line-height: 1.5;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .quiz-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .quiz-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .result-row {
    overflow-wrap: anywhere;
  }
}
</style>
