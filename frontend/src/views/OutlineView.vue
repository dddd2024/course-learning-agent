<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  Collection,
  Document,
  MagicStick,
  Refresh,
} from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import { MAX_PAGE_SIZE } from '../constants/pagination'
import {
  generateKnowledgePoints,
  listKnowledgePoints,
  type KnowledgePoint,
} from '../api/knowledge'
import {
  getChunks,
  listMaterials,
  type Chunk,
  type Material,
} from '../api/material'
import { recordTaskEvent, verifyTask } from '../api/plan'
import { parseApiError } from '../utils/error'
import EmptyState from '../components/common/EmptyState.vue'

interface ChunkWithSource {
  chunk: Chunk
  materialName: string
}

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))

const course = ref<Course | null>(null)
const courseLoading = ref(false)

const knowledgePoints = ref<KnowledgePoint[]>([])
const listLoading = ref(false)
const generating = ref(false)

const chunkDialogVisible = ref(false)
const chunkDialogLoading = ref(false)
const currentChunkId = ref<number | null>(null)
const currentChunk = ref<Chunk | null>(null)
const currentChunkMaterialName = ref<string>('')

const sourceListDialogVisible = ref(false)
const sourceListLoading = ref(false)
const currentSourceKp = ref<KnowledgePoint | null>(null)
const sourceListChunks = ref<ChunkWithSource[]>([])

const materialChunksCache = ref<Map<number, Chunk[]>>(new Map())
const reviewTaskId = computed(() => Number(route.query.task_id || 0))
const targetKnowledgePointId = computed(() => Number(route.query.knowledge_point_id || 0))
const targetResolved = ref(false)
const completingReview = ref(false)

function normalizeImportance(value: number | undefined | null): number {
  if (value === undefined || value === null || Number.isNaN(value)) return 0
  const v = Math.round(value)
  if (v < 0) return 0
  if (v > 5) return 5
  return v
}

function importanceTagType(
  importance: number,
): 'info' | 'success' | 'warning' | 'danger' {
  const v = normalizeImportance(importance)
  if (v >= 5) return 'danger'
  if (v >= 4) return 'warning'
  if (v >= 3) return 'success'
  return 'info'
}

function importanceLabel(importance: number): string {
  const v = normalizeImportance(importance)
  if (v >= 5) return '核心'
  if (v >= 4) return '重要'
  if (v >= 3) return '中等'
  if (v >= 2) return '一般'
  if (v >= 1) return '了解'
  return '未评级'
}

async function fetchCourse() {
  if (!courseId.value) {
    ElMessage.error('课程 ID 无效')
    router.push('/courses')
    return
  }
  courseLoading.value = true
  try {
    const { data } = await getCourse(courseId.value)
    course.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取课程详情失败'))
    router.push('/courses')
  } finally {
    courseLoading.value = false
  }
}

async function fetchKnowledgePoints() {
  if (!courseId.value) return
  listLoading.value = true
  try {
    const { data } = await listKnowledgePoints(courseId.value)
    knowledgePoints.value = data.items
    const target = knowledgePoints.value.find((item) => item.id === targetKnowledgePointId.value)
    if (reviewTaskId.value && !target) {
      const archived = await listKnowledgePoints(courseId.value, { include_archived: true })
      const archivedTarget = archived.data.items.find((item) => item.id === targetKnowledgePointId.value)
      if (!archivedTarget) {
        ElMessage.error('复习任务目标不存在，无法完成该任务')
        return
      }
      targetResolved.value = true
      await recordTaskEvent(reviewTaskId.value, 'target_loaded', Number(archivedTarget.id))
      ElMessage.warning('复习目标已更新到当前提纲版本，请确认内容后完成复习')
      return
    }
    if (reviewTaskId.value && target) {
      targetResolved.value = true
      await recordTaskEvent(reviewTaskId.value, 'target_loaded', Number(target.id))
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取知识点列表失败'))
    knowledgePoints.value = []
  } finally {
    listLoading.value = false
  }
}

async function handleGenerate() {
  if (!courseId.value) return
  const replacingExisting = knowledgePoints.value.length > 0
  const confirmationMessage = replacingExisting
    ? `将归档现有 ${knowledgePoints.value.length} 个知识点并生成新版本。旧版本知识点仍可通过历史记录查看，关联的测验薄弱点记录将保留。是否继续？`
    : '将基于课程资料自动生成知识点提纲，可能需要一些时间，是否继续？'
  try {
    await ElMessageBox.confirm(
      confirmationMessage,
      replacingExisting ? '重新生成知识点' : '生成知识点',
      {
        type: replacingExisting ? 'warning' : 'info',
        confirmButtonText: replacingExisting ? '归档并生成' : '生成',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  generating.value = true
  try {
    const { data } = await generateKnowledgePoints(courseId.value)
    knowledgePoints.value = data.knowledge_points
    materialChunksCache.value.clear()
    ElMessage.success(`已生成 ${data.count} 个知识点`)
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成知识点失败'))
  } finally {
    generating.value = false
  }
}

async function fetchAllChunks(): Promise<ChunkWithSource[]> {
  const result: ChunkWithSource[] = []
  const { data: materialsData } = await listMaterials(courseId.value)
  const readyMaterials: Material[] = materialsData.items.filter(
    (m) => m.status === 'ready',
  )
  for (const m of readyMaterials) {
    let chunks = materialChunksCache.value.get(m.id)
    if (!chunks) {
      try {
        const { data } = await getChunks(m.id, { page: 1, page_size: MAX_PAGE_SIZE })
        chunks = data.items
        materialChunksCache.value.set(m.id, chunks)
      } catch {
        continue
      }
    }
    for (const c of chunks) {
      result.push({ chunk: c, materialName: m.filename })
    }
  }
  return result
}

async function openChunkDialog(chunkId: number) {
  currentChunkId.value = chunkId
  currentChunk.value = null
  currentChunkMaterialName.value = ''
  chunkDialogVisible.value = true
  chunkDialogLoading.value = true
  try {
    const all = await fetchAllChunks()
    const found = all.find((c) => c.chunk.id === chunkId)
    if (found) {
      currentChunk.value = found.chunk
      currentChunkMaterialName.value = found.materialName
    }
  } catch {
    // 静默失败，仅展示 ID
  } finally {
    chunkDialogLoading.value = false
  }
}

async function openSourceListDialog(kp: KnowledgePoint) {
  currentSourceKp.value = kp
  sourceListDialogVisible.value = true
  sourceListLoading.value = true
  sourceListChunks.value = []
  try {
    const all = await fetchAllChunks()
    const idSet = new Set(kp.source_chunk_ids)
    sourceListChunks.value = all.filter((c) => idSet.has(c.chunk.id))
  } catch {
    // 静默失败
  } finally {
    sourceListLoading.value = false
  }
}

function goBack() {
  router.push(`/courses/${courseId.value}`)
}

function goToLearn() {
  router.push(`/courses/${courseId.value}/learn`)
}

function goToLearnWithKp(kp: KnowledgePoint) {
  const sourceChunkIds = kp.source_chunk_ids || []
  router.push({
    path: `/courses/${courseId.value}/learn`,
    query: {
      kp_title: kp.title,
      kp_summary: kp.summary || '',
      kp_source_chunk_ids: sourceChunkIds.length > 0 ? JSON.stringify(sourceChunkIds) : '',
    },
  })
}

async function completeReview() {
  if (!reviewTaskId.value || !targetResolved.value) return
  completingReview.value = true
  try {
    const { data } = await verifyTask(reviewTaskId.value, true)
    if (!data.verified) throw new Error('服务端尚未验证复习完成')
    ElMessage.success('复习任务已完成')
    router.push('/plans')
  } catch (err) {
    ElMessage.error(parseApiError(err, '复习任务验证失败'))
  } finally {
    completingReview.value = false
  }
}

onMounted(async () => {
  await fetchCourse()
  if (course.value) {
    await fetchKnowledgePoints()
  }
})
</script>

<template>
  <div v-loading="courseLoading" class="page">
    <div class="header">
      <el-button :icon="ArrowLeft" @click="goBack">返回课程详情</el-button>
      <div v-if="course" class="course-brief">
        <span class="course-name">{{ course.name }}</span>
        <span v-if="course.teacher" class="course-meta">
          教师：{{ course.teacher }}
        </span>
      </div>
    </div>

    <el-card class="section-card" shadow="never">
      <div class="action-bar">
        <div class="action-info">
          <el-icon :size="22" color="#409eff"><Collection /></el-icon>
          <div>
            <div class="action-title">知识点提纲</div>
            <div class="action-desc">
              基于课程资料自动梳理核心知识点，生成复习提纲与建议任务
            </div>
          </div>
        </div>
        <div class="action-buttons">
          <el-button
            :icon="Refresh"
            :loading="listLoading"
            :disabled="generating"
            @click="fetchKnowledgePoints"
          >
            刷新
          </el-button>
          <el-button
            type="primary"
            :icon="MagicStick"
            :loading="generating"
            @click="handleGenerate"
          >
            {{
              generating
                ? '生成中...'
                : knowledgePoints.length > 0
                  ? '重新生成知识点'
                  : '生成知识点'
            }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-alert
      v-if="reviewTaskId"
      :title="targetResolved ? '已定位任务目标，请完成本次复习后提交验证' : '正在解析复习任务目标'"
      :type="targetResolved ? 'success' : 'warning'"
      :closable="false"
      class="section-card"
    />
    <el-button
      v-if="reviewTaskId"
      type="primary"
      :disabled="!targetResolved"
      :loading="completingReview"
      @click="completeReview"
    >完成本次复习</el-button>

    <el-card
      v-if="!listLoading && knowledgePoints.length === 0"
      class="section-card"
      shadow="never"
    >
      <EmptyState
        :icon="MagicStick"
        title="还没有知识点"
        description="点击上方按钮生成知识点大纲"
        action-text="生成知识点"
        @action="handleGenerate"
      />
    </el-card>

    <el-card
      v-if="knowledgePoints.length > 0"
      v-loading="listLoading"
      class="section-card"
      shadow="never"
    >
      <template #header>
        <div class="section-title-bar">
          <span class="section-title">知识点列表</span>
          <span class="section-count">共 {{ knowledgePoints.length }} 个知识点</span>
        </div>
      </template>
      <div class="kp-list">
        <div
          v-for="(kp, idx) in knowledgePoints"
          :key="idx"
          class="kp-card kp-card--clickable"
          :class="{ 'kp-card--target': kp.id === targetKnowledgePointId }"
          role="link"
          tabindex="0"
          :aria-label="`学习知识点：${kp.title}`"
          @click="goToLearnWithKp(kp)"
          @keydown.enter.self="goToLearnWithKp(kp)"
          @keydown.space.self.prevent="goToLearnWithKp(kp)"
        >
          <div class="kp-head">
            <div class="kp-num">{{ idx + 1 }}</div>
            <div class="kp-title kp-title--link">{{ kp.title }}</div>
            <div class="kp-importance">
              <el-rate
                :model-value="normalizeImportance(kp.importance)"
                disabled
                :max="5"
                size="small"
              />
              <el-tag
                :type="importanceTagType(kp.importance)"
                size="small"
                effect="light"
              >
                {{ importanceLabel(kp.importance) }}
              </el-tag>
            </div>
          </div>
          <div class="kp-summary">{{ kp.summary }}</div>
          <div class="kp-meta">
            <div class="kp-meta-item">
              <span class="kp-meta-label">考法：</span>
              <span class="kp-meta-value">{{ kp.exam_style || '—' }}</span>
            </div>
            <div class="kp-meta-item">
              <span class="kp-meta-label">建议任务：</span>
              <el-button
                link
                type="primary"
                class="kp-meta-value"
                :aria-label="`开始复习任务：${kp.review_action || kp.title}`"
                @click.stop="goToLearn"
              >
                {{ kp.review_action || '—' }}
              </el-button>
            </div>
          </div>
          <div class="kp-foot">
            <span class="kp-source-label">来源片段：</span>
            <template
              v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0"
            >
              <span class="kp-source-count">
                共 {{ kp.source_chunk_ids.length }} 个片段
              </span>
              <el-button
                link
                type="primary"
                size="small"
                :aria-label="`查看 ${kp.title} 的来源片段`"
                @click.stop="openSourceListDialog(kp)"
              >
                查看来源
              </el-button>
            </template>
            <span v-else class="kp-source-empty">无</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-card
      v-if="knowledgePoints.length > 0"
      class="section-card"
      shadow="never"
    >
      <template #header>
        <div class="section-title-bar">
          <span class="section-title">复习提纲</span>
          <span class="section-count">结构化复习要点</span>
        </div>
      </template>
      <div class="outline">
        <div class="outline-header">
          <el-icon :size="18" color="#409eff"><Document /></el-icon>
          <span class="outline-title-text">
            {{ course?.name }} · 复习提纲
          </span>
        </div>
        <ol class="outline-list">
          <li
            v-for="(kp, idx) in knowledgePoints"
            :key="idx"
            class="outline-item"
          >
            <div class="outline-item-head">
              <span class="outline-num">{{ idx + 1 }}.</span>
              <span class="outline-item-title-text">{{ kp.title }}</span>
              <el-tag
                :type="importanceTagType(kp.importance)"
                size="small"
                effect="light"
              >
                {{ importanceLabel(kp.importance) }}
              </el-tag>
            </div>
            <div class="outline-summary">{{ kp.summary }}</div>
            <ul class="outline-sub">
              <li>
                <strong>考法：</strong>
                <span>{{ kp.exam_style || '—' }}</span>
              </li>
              <li>
                <strong>建议任务：</strong>
                <span>{{ kp.review_action || '—' }}</span>
              </li>
              <li v-if="kp.source_chunk_ids && kp.source_chunk_ids.length > 0">
                <strong>来源片段：</strong>
                <span>共 {{ kp.source_chunk_ids.length }} 个片段</span>
              </li>
            </ul>
          </li>
        </ol>
      </div>
    </el-card>

    <el-dialog
      v-model="chunkDialogVisible"
      :title="
        currentChunkId !== null ? `来源片段 #${currentChunkId}` : '来源片段'
      "
      width="min(640px, calc(100vw - 32px))"
    >
      <div v-loading="chunkDialogLoading" class="chunk-dialog-body">
        <template v-if="currentChunk">
          <div class="chunk-dialog-section">
            <div class="chunk-dialog-label">所属资料</div>
            <div class="chunk-dialog-value">{{ currentChunkMaterialName }}</div>
          </div>
          <div class="chunk-dialog-section">
            <div class="chunk-dialog-label">片段标题</div>
            <div class="chunk-dialog-value">
              {{ currentChunk.title || '（无标题）' }}
            </div>
          </div>
          <div class="chunk-dialog-section">
            <div class="chunk-dialog-label">页码</div>
            <div class="chunk-dialog-value">第 {{ currentChunk.page_no }} 页</div>
          </div>
          <div class="chunk-dialog-section">
            <div class="chunk-dialog-label">片段内容</div>
            <div class="chunk-dialog-text">{{ currentChunk.text }}</div>
          </div>
        </template>
        <el-empty
          v-else-if="!chunkDialogLoading"
          :description="
            currentChunkId !== null
              ? `未找到片段 #${currentChunkId} 的详细内容`
              : '未找到片段详细内容'
          "
          :image-size="80"
        />
      </div>
    </el-dialog>

    <el-dialog
      v-model="sourceListDialogVisible"
      :title="
        currentSourceKp
          ? `来源片段 — ${currentSourceKp.title}（共 ${currentSourceKp.source_chunk_ids?.length || 0} 个）`
          : '来源片段'
      "
      width="min(720px, calc(100vw - 32px))"
    >
      <div v-loading="sourceListLoading" class="source-list-body">
        <template v-if="sourceListChunks.length > 0">
          <div
            v-for="item in sourceListChunks"
            :key="item.chunk.id"
            class="source-list-item"
            role="button"
            tabindex="0"
            :aria-label="`查看来源片段 #${item.chunk.id}`"
            @click="openChunkDialog(item.chunk.id)"
            @keydown.enter="openChunkDialog(item.chunk.id)"
            @keydown.space.prevent="openChunkDialog(item.chunk.id)"
          >
            <div class="source-list-item-head">
              <span class="source-list-item-id">#{{ item.chunk.id }}</span>
              <span class="source-list-item-material">{{ item.materialName }}</span>
              <span v-if="item.chunk.page_no" class="source-list-item-page">
                第 {{ item.chunk.page_no }} 页
              </span>
            </div>
            <div class="source-list-item-text">
              {{ item.chunk.text?.substring(0, 120) }}{{ item.chunk.text && item.chunk.text.length > 120 ? '…' : '' }}
            </div>
          </div>
        </template>
        <el-empty
          v-else-if="!sourceListLoading"
          description="未找到来源片段详情"
          :image-size="80"
        />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  background: #fff;
  padding: 24px;
  border-radius: 4px;
}

.header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.course-brief {
  display: flex;
  align-items: center;
  gap: 12px;
}

.course-name {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.course-meta {
  font-size: 13px;
  color: #909399;
}

.section-card {
  margin-bottom: 20px;
}

.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.action-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.action-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.action-desc {
  font-size: 13px;
  color: #909399;
  margin-top: 2px;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.section-count {
  font-size: 13px;
  color: #909399;
}

.kp-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kp-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.kp-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 10px rgba(64, 158, 255, 0.08);
}

.kp-card--clickable {
  cursor: pointer;
}

.kp-card--target {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.kp-card--clickable:focus-visible,
.source-list-item:focus-visible {
  outline: 3px solid rgba(64, 158, 255, 0.4);
  outline-offset: 2px;
  border-color: #409eff;
}

.kp-title--link {
  color: #303133;
  transition: color 0.2s;
}

.kp-card--clickable:hover .kp-title--link {
  color: #409eff;
}

.kp-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.kp-num {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #ecf5ff;
  color: #409eff;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.kp-title {
  flex: 1;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kp-importance {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.kp-summary {
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 12px;
}

.kp-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.kp-meta-item {
  font-size: 13px;
  line-height: 1.6;
}

.kp-meta-label {
  color: #909399;
  font-weight: 600;
}

.kp-meta-value {
  color: #606266;
}

.kp-foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px dashed #ebeef5;
}

.kp-source-label {
  font-size: 13px;
  color: #909399;
}

.kp-source-tag {
  cursor: pointer;
}

.kp-source-tag:hover {
  color: #409eff;
  border-color: #409eff;
}

.kp-source-empty {
  font-size: 13px;
  color: #c0c4cc;
}

.kp-source-count {
  font-size: 13px;
  color: #606266;
}

.source-list-body {
  max-height: 500px;
  overflow-y: auto;
}

.source-list-item {
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.source-list-item:hover {
  border-color: #409eff;
  background: #f0f7ff;
}

.source-list-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.source-list-item-id {
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
}

.source-list-item-material {
  font-size: 12px;
  color: #909399;
}

.source-list-item-page {
  font-size: 12px;
  color: #c0c4cc;
}

.source-list-item-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.outline {
  background: #fafafa;
  border-radius: 6px;
  padding: 18px 22px;
}

.outline-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}

.outline-title-text {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.outline-list {
  list-style: none;
  padding: 0;
  margin: 0;
  counter-reset: outline-counter;
}

.outline-item {
  margin-bottom: 18px;
}

.outline-item:last-child {
  margin-bottom: 0;
}

.outline-item-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.outline-num {
  font-size: 15px;
  font-weight: 600;
  color: #409eff;
  flex-shrink: 0;
}

.outline-item-title-text {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  flex: 1;
}

.outline-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 6px;
  padding-left: 18px;
}

.outline-sub {
  list-style: disc;
  padding-left: 36px;
  margin: 0;
}

.outline-sub li {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
}

.outline-sub strong {
  color: #303133;
}

.chunk-dialog-body {
  min-height: 120px;
}

.chunk-dialog-section {
  margin-bottom: 16px;
}

.chunk-dialog-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.chunk-dialog-value {
  font-size: 14px;
  color: #303133;
}

.chunk-dialog-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  max-height: 320px;
  overflow-y: auto;
  word-break: break-word;
}

@media (max-width: 768px) {
  .page {
    padding: 12px;
  }

  .header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .course-brief {
    min-width: 0;
    flex-wrap: wrap;
    gap: 4px 10px;
  }

  .course-name {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .section-card {
    margin-bottom: 14px;
  }

  .action-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
  }

  .action-info {
    align-items: flex-start;
  }

  .action-desc {
    line-height: 1.5;
  }

  .action-buttons {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    width: 100%;
  }

  .action-buttons > .el-button {
    width: 100%;
    min-width: 0;
    margin-left: 0;
    padding-inline: 8px;
    white-space: nowrap;
  }

  .section-title-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }

  .kp-list {
    gap: 12px;
  }

  .kp-card {
    padding: 14px;
  }

  .kp-head {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr);
    align-items: start;
    gap: 8px 10px;
  }

  .kp-title {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    overflow-wrap: anywhere;
    line-height: 1.45;
  }

  .kp-importance {
    grid-column: 2;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 6px;
  }

  .kp-meta-item {
    overflow-wrap: anywhere;
  }

  .kp-meta-value.el-button {
    height: auto;
    max-width: 100%;
    padding: 0;
    white-space: normal;
    text-align: left;
    vertical-align: top;
  }

  .kp-foot {
    align-items: flex-start;
  }

  .outline {
    padding: 14px;
  }

  .outline-header {
    align-items: flex-start;
  }

  .outline-title-text {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .outline-item-head {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr);
    align-items: start;
    gap: 5px 6px;
  }

  .outline-item-title-text {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .outline-item-head > .el-tag {
    grid-column: 2;
    justify-self: start;
  }

  .outline-summary {
    padding-left: 0;
    overflow-wrap: anywhere;
  }

  .outline-sub {
    padding-left: 20px;
  }

  .outline-sub li,
  .source-list-item-text,
  .source-list-item-material {
    overflow-wrap: anywhere;
  }

  .source-list-item-head {
    align-items: flex-start;
    flex-wrap: wrap;
  }
}
</style>
