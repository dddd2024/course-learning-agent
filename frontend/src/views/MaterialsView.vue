<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { ArrowLeft, Search, UploadFilled, View } from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import {
  deleteMaterial,
  getChunks,
  getMaterialOverview,
  listMaterials,
  parseMaterial,
  search,
  uploadMaterial,
  type Chunk,
  type Material,
  type MaterialOverview,
  type MaterialStatus,
  type SearchItem,
} from '../api/material'
import { parseApiError } from '../utils/error'
import { formatLocalDateTime, secondsSince } from '../utils/datetime'

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))

const course = ref<Course | null>(null)
const courseLoading = ref(false)

const materials = ref<Material[]>([])
const tableLoading = ref(false)

interface UploadTask {
  uid: number
  filename: string
  percent: number
  status: 'uploading' | 'success' | 'error'
  error?: string
}
const uploadTasks = ref<UploadTask[]>([])

const acceptTypes = '.txt,.pdf,.docx,.pptx,.md'
const allowedExtensions = ['txt', 'pdf', 'docx', 'pptx', 'md']

const statusFilter = ref<MaterialStatus | ''>('')

const statusTagType: Record<MaterialStatus, 'info' | 'warning' | 'success' | 'danger'> = {
  uploaded: 'info',
  processing: 'warning',
  ready: 'success',
  failed: 'danger',
}
const statusLabel: Record<MaterialStatus, string> = {
  uploaded: '已上传',
  processing: '解析中',
  ready: '已就绪',
  failed: '解析失败',
}

// P0: a "ready" material with a non-empty error_message means the latest
// re-parse failed but the previous chunks are still usable. Show a
// distinct label + tooltip so the user knows the result is stale.
function isStaleReady(m: Material): boolean {
  return m.status === 'ready' && !!m.error_message
}

function staleReadyLabel(): string {
  return '已就绪（上次解析失败）'
}

const chunksDialogVisible = ref(false)
const chunksLoading = ref(false)
const chunks = ref<Chunk[]>([])
const chunksTotal = ref(0)
const chunksPage = ref(1)
const chunksPageSize = ref(10)
const currentMaterial = ref<Material | null>(null)

// Phase 2 Task C/D: material overview (stats + security findings).
const materialOverview = ref<MaterialOverview | null>(null)

const searchKeyword = ref('')
const searchLoading = ref(false)
const searchResults = ref<SearchItem[]>([])
const searchTotal = ref(0)
const searched = ref(false)
const expandedSearchIds = ref<Set<number>>(new Set())

let pollTimer: ReturnType<typeof setInterval> | null = null

function getFileExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx >= 0 ? filename.slice(idx + 1).toLowerCase() : ''
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

async function fetchMaterials() {
  if (!courseId.value) return
  tableLoading.value = true
  try {
    const { data } = await listMaterials(courseId.value, {
      status: statusFilter.value || undefined,
    })
    materials.value = data.items
    ensurePolling()
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料列表失败'))
  } finally {
    tableLoading.value = false
  }
}

function hasProcessing(): boolean {
  return materials.value.some((m) => m.status === 'processing')
}

function ensurePolling() {
  if (hasProcessing()) {
    startPolling()
  } else {
    stopPolling()
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasProcessing()) {
      stopPolling()
      return
    }
    try {
      const { data } = await listMaterials(courseId.value)
      const map = new Map(data.items.map((m) => [m.id, m]))
      const updated: Material[] = materials.value.map((m) => {
        const fresh = map.get(m.id)
        return fresh ?? m
      })
      materials.value = updated
      if (!hasProcessing()) {
        stopPolling()
      }
    } catch {
      // 静默失败，下次轮询继续
    }
  }, 2500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function beforeUpload(file: File): boolean {
  const ext = getFileExtension(file.name)
  if (!allowedExtensions.includes(ext)) {
    ElMessage.warning(`不支持的文件类型：${ext || '未知'}，仅支持 ${allowedExtensions.join('、')}`)
    return false
  }
  return true
}

function customUpload(options: UploadRequestOptions): Promise<unknown> {
  const file = options.file as File
  const task: UploadTask = {
    uid: options.file.uid,
    filename: file.name,
    percent: 0,
    status: 'uploading',
  }
  uploadTasks.value.push(task)
  return uploadMaterial(courseId.value, file, {
    onUploadProgress: (event) => {
      if (event.total) {
        task.percent = Math.round((event.loaded / event.total) * 100)
      }
    },
  })
    .then((res) => {
      task.status = 'success'
      task.percent = 100
      ElMessage.success(`「${file.name}」上传成功，正在处理`)
      // Auto-parse: trigger processing immediately so the user never has
      // to click "parse" manually. The parse endpoint is a separate call
      // so upload success and parse success stay independent (a parse
      // failure does not roll back the upload).
      const materialId = res.data.id
      parseMaterial(materialId)
        .then(() => {
          ensurePolling()
        })
        .catch(() => {
          // Parse failure is surfaced via status refresh; do not block.
          fetchMaterials()
        })
      return res
    })
    .catch((err) => {
      task.status = 'error'
      task.error = parseApiError(err, '上传失败')
      ElMessage.error(`「${file.name}」上传失败：${task.error}`)
      throw err
    })
    .finally(() => {
      setTimeout(() => {
        uploadTasks.value = uploadTasks.value.filter((t) => t.uid !== task.uid)
      }, 2000)
      fetchMaterials()
    })
}

function clearFinishedTasks() {
  uploadTasks.value = uploadTasks.value.filter((t) => t.status === 'uploading')
}

async function handleParse(material: Material) {
  try {
    await ElMessageBox.confirm(
      `确定处理资料「${material.filename}」吗？`,
      '处理确认',
      { type: 'info', confirmButtonText: '处理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const { data } = await parseMaterial(material.id)
    const idx = materials.value.findIndex((m) => m.id === material.id)
    if (idx >= 0) {
      materials.value[idx] = {
        ...materials.value[idx],
        status: data.status,
      }
    }
    // The parse response omits error_message, so re-fetch the list to
    // surface the "stale ready" warning (status=ready + error_message)
    // or the failure reason (status=failed) on the row.
    await fetchMaterials()
    if (data.status === 'ready') {
      ElMessage.success(`处理完成，共生成 ${data.chunk_count} 个片段`)
    } else if (data.status === 'failed') {
      ElMessage.warning('处理失败，请查看状态标签了解详情')
    } else {
      ElMessage.success(`已提交处理，预计生成 ${data.chunk_count} 个片段`)
      ensurePolling()
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '处理请求失败'))
  }
}

function goToLogs(material: Material) {
  router.push({ path: '/logs', query: { material_id: String(material.id) } })
}

async function handleDelete(material: Material) {
  try {
    await ElMessageBox.confirm(
      `确定删除资料「${material.filename}」吗？删除后将同时清理其片段与原始文件，且不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteMaterial(material.id)
    // If the deleted material was open in the chunks dialog, close it so
    // we never reference a material that no longer exists.
    if (currentMaterial.value && currentMaterial.value.id === material.id) {
      currentMaterial.value = null
      chunksDialogVisible.value = false
    }
    ElMessage.success(`「${material.filename}」已删除`)
    fetchMaterials()
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除失败'))
  }
}

async function openChunksDialog(material: Material) {
  currentMaterial.value = material
  materialOverview.value = null
  chunksDialogVisible.value = true
  chunksPage.value = 1
  await Promise.all([fetchChunks(), fetchOverview(material.id)])
}

async function fetchOverview(materialId: number) {
  try {
    const { data } = await getMaterialOverview(materialId)
    materialOverview.value = data
  } catch {
    // 静默失败，不影响片段查看
    materialOverview.value = null
  }
}

function pageRangeText(range: number[] | null): string {
  if (!range || range.length === 0) return '无'
  if (range.length === 1) return `第 ${range[0]} 页`
  return `第 ${range[0]} - ${range[range.length - 1]} 页`
}

async function fetchChunks() {
  if (!currentMaterial.value) return
  chunksLoading.value = true
  try {
    const { data } = await getChunks(currentMaterial.value.id, {
      page: chunksPage.value,
      page_size: chunksPageSize.value,
    })
    chunks.value = data.items
    chunksTotal.value = data.total
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取片段列表失败'))
    chunks.value = []
    chunksTotal.value = 0
  } finally {
    chunksLoading.value = false
  }
}

function handleChunksPageChange(page: number) {
  chunksPage.value = page
  fetchChunks()
}

function handleChunksPageSizeChange(size: number) {
  chunksPageSize.value = size
  chunksPage.value = 1
  fetchChunks()
}

async function handleSearch() {
  const kw = searchKeyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入关键词')
    return
  }
  if (!courseId.value) return
  searchLoading.value = true
  searched.value = true
  expandedSearchIds.value.clear()
  try {
    const { data } = await search({
      course_id: courseId.value,
      keyword: kw,
      top_k: 12,
    })
    searchResults.value = data.items
    searchTotal.value = data.total
    if (data.items.length === 0) {
      ElMessage.info('未找到相关片段')
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '检索失败'))
    searchResults.value = []
    searchTotal.value = 0
  } finally {
    searchLoading.value = false
  }
}

function toggleSearchExpand(id: number) {
  if (expandedSearchIds.value.has(id)) {
    expandedSearchIds.value.delete(id)
  } else {
    expandedSearchIds.value.add(id)
  }
}

function truncate(text: string, max = 120): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}

function formatPercent(percent: number): string {
  return `${percent}%`
}

function goBack() {
  router.push(`/courses/${courseId.value}`)
}

onMounted(async () => {
  await fetchCourse()
  await fetchMaterials()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div v-loading="courseLoading" class="page">
    <div class="header">
      <el-button :icon="ArrowLeft" @click="goBack">返回课程详情</el-button>
      <div v-if="course" class="course-brief">
        <span class="course-name">{{ course.name }}</span>
        <span v-if="course.teacher" class="course-meta">教师：{{ course.teacher }}</span>
      </div>
    </div>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title">上传资料</div>
      </template>
      <el-upload
        drag
        multiple
        :accept="acceptTypes"
        :show-file-list="false"
        :auto-upload="true"
        :http-request="customUpload"
        :before-upload="beforeUpload"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="upload-tip">
            支持 txt、pdf、docx、pptx、md 格式，可多文件上传
          </div>
        </template>
      </el-upload>

      <div v-if="uploadTasks.length > 0" class="upload-tasks">
        <div v-for="task in uploadTasks" :key="task.uid" class="upload-task">
          <div class="upload-task-head">
            <span class="upload-task-name">{{ task.filename }}</span>
            <el-tag
              v-if="task.status === 'uploading'"
              type="warning"
              size="small"
            >
              上传中 {{ formatPercent(task.percent) }}
            </el-tag>
            <el-tag v-else-if="task.status === 'success'" type="success" size="small">
              完成
            </el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </div>
          <el-progress
            :percentage="task.percent"
            :status="task.status === 'error' ? 'exception' : task.status === 'success' ? 'success' : undefined"
          />
        </div>
        <div class="upload-tasks-actions">
          <el-button text size="small" @click="clearFinishedTasks">清除已完成</el-button>
        </div>
      </div>
    </el-card>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title-bar">
          <span class="section-title">资料列表</span>
          <div class="section-actions">
            <el-select
              v-model="statusFilter"
              placeholder="状态筛选"
              clearable
              size="default"
              style="width: 140px"
              @change="fetchMaterials"
            >
              <el-option label="已上传" value="uploaded" />
              <el-option label="解析中" value="processing" />
              <el-option label="已就绪" value="ready" />
              <el-option label="解析失败" value="failed" />
            </el-select>
            <el-button @click="fetchMaterials">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table
        v-loading="tableLoading"
        :data="materials"
        stripe
        empty-text="暂无资料，请上传文件"
      >
        <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="100" />
        <el-table-column label="状态" width="180">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.status === 'failed' && row.error_message"
              :content="row.error_message"
              placement="top"
            >
              <el-tag :type="statusTagType[row.status as MaterialStatus]">
                {{ statusLabel[row.status as MaterialStatus] }}
              </el-tag>
            </el-tooltip>
            <el-tooltip
              v-else-if="isStaleReady(row)"
              :content="row.error_message"
              placement="top"
            >
              <el-tag type="warning">
                {{ staleReadyLabel() }}
              </el-tag>
            </el-tooltip>
            <template v-else-if="row.status === 'processing'">
              <el-tag :type="statusTagType[row.status as MaterialStatus]">
                {{ statusLabel[row.status as MaterialStatus] }}
              </el-tag>
              <span v-if="row.parse_started_at" class="elapsed-hint">
                已耗时 {{ secondsSince(row.parse_started_at) }} 秒
              </span>
            </template>
            <el-tag v-else :type="statusTagType[row.status as MaterialStatus]">
              {{ statusLabel[row.status as MaterialStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" align="center" />
        <el-table-column label="上传时间" width="180">
          <template #default="{ row }">
            {{ formatLocalDateTime(row.uploaded_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :disabled="row.status === 'processing'"
              @click="handleParse(row)"
            >
              {{ row.status === 'uploaded' ? '处理' : '重新处理' }}
            </el-button>
            <el-button
              size="small"
              :icon="View"
              :disabled="row.status !== 'ready'"
              @click="openChunksDialog(row)"
            >
              查看片段
            </el-button>
            <el-button
              v-if="row.status === 'failed'"
              size="small"
              type="warning"
              @click="goToLogs(row)"
            >
              查看原因
            </el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="row.status === 'processing'"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-title-bar">
          <span class="section-title">资料检索</span>
        </div>
      </template>
      <div class="search-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="输入关键词检索课程资料片段"
          clearable
          class="search-input"
          @keyup.enter="handleSearch"
        />
        <el-button
          type="primary"
          :icon="Search"
          :loading="searchLoading"
          @click="handleSearch"
        >
          检索
        </el-button>
      </div>

      <div v-if="searched" class="search-results">
        <div class="search-results-head">
          共找到 {{ searchTotal }} 条结果
        </div>
        <el-empty
          v-if="searchResults.length === 0 && !searchLoading"
          description="未找到相关片段"
        />
        <div
          v-for="item in searchResults"
          :key="item.chunk_id"
          class="search-item"
          @click="toggleSearchExpand(item.chunk_id)"
        >
          <div class="search-item-head">
            <span class="search-item-name">{{ item.filename }}</span>
            <el-tag size="small" type="info">第 {{ item.page_no }} 页</el-tag>
            <span v-if="item.title" class="search-item-title">{{ item.title }}</span>
          </div>
          <div class="search-item-text">
            <template v-if="expandedSearchIds.has(item.chunk_id)">
              {{ item.text }}
            </template>
            <template v-else>
              {{ truncate(item.text) }}
            </template>
          </div>
          <div class="search-item-foot">
            <el-button text size="small">
              {{ expandedSearchIds.has(item.chunk_id) ? '收起' : '展开全文' }}
            </el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-dialog
      v-model="chunksDialogVisible"
      :title="currentMaterial ? `片段列表 - ${currentMaterial.filename}` : '片段列表'"
      width="760px"
      @closed="
        () => {
          currentMaterial = null
          materialOverview = null
        }
      "
    >
      <div v-if="materialOverview" class="overview-panel">
        <el-alert
          v-if="currentMaterial && isStaleReady(currentMaterial)"
          title="最近一次重新解析失败，当前展示的是上一版解析结果"
          type="warning"
          :closable="false"
          show-icon
          class="overview-alert"
        />
        <div class="overview-stats">
          <div class="overview-stat">
            <span class="stat-label">片段数</span>
            <span class="stat-value">{{ materialOverview.chunk_count }}</span>
          </div>
          <div class="overview-stat">
            <span class="stat-label">页码范围</span>
            <span class="stat-value">{{ pageRangeText(materialOverview.page_range) }}</span>
          </div>
          <div class="overview-stat">
            <span class="stat-label">章节数</span>
            <span class="stat-value">{{ materialOverview.section_count }}</span>
          </div>
          <div
            v-if="materialOverview.security_findings_count > 0"
            class="overview-stat stat-warning"
          >
            <span class="stat-label">安全提示</span>
            <span class="stat-value">
              {{ materialOverview.security_findings_count }} 处可疑注入
            </span>
          </div>
        </div>
        <div
          v-if="materialOverview.keywords.length > 0"
          class="overview-keywords"
        >
          <span class="overview-section-label">高频关键词</span>
          <div class="keyword-tags">
            <el-tag
              v-for="kw in materialOverview.keywords"
              :key="kw"
              size="small"
              effect="plain"
              class="keyword-tag"
            >
              {{ kw }}
            </el-tag>
          </div>
        </div>
        <el-alert
          v-if="materialOverview.security_findings_count > 0"
          title="检测到疑似 Prompt 注入"
          type="warning"
          :closable="false"
          show-icon
          class="overview-alert"
        >
          资料中检测到 {{ materialOverview.security_findings_count }} 处疑似
          Prompt 注入模式，已自动隔离并在问答中加入防护提示。
        </el-alert>
        <el-alert
          v-if="materialOverview.warnings.length > 0"
          v-for="(w, wi) in materialOverview.warnings"
          :key="wi"
          :title="w"
          type="info"
          :closable="false"
          show-icon
          class="overview-alert"
        />
      </div>
      <el-table
        v-loading="chunksLoading"
        :data="chunks"
        max-height="420"
        stripe
        empty-text="暂无片段"
      >
        <el-table-column prop="chunk_index" label="序号" width="80" align="center" />
        <el-table-column prop="title" label="标题" width="180" show-overflow-tooltip />
        <el-table-column prop="page_no" label="页码" width="80" align="center" />
        <el-table-column label="内容">
          <template #default="{ row }">
            <div class="chunk-text">{{ row.text }}</div>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="chunksTotal > 0" class="chunks-pagination">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="chunksTotal"
          :current-page="chunksPage"
          :page-size="chunksPageSize"
          :page-sizes="[10, 20, 50]"
          @current-change="handleChunksPageChange"
          @size-change="handleChunksPageSizeChange"
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

.elapsed-hint {
  display: block;
  font-size: 12px;
  color: #e6a23c;
  margin-top: 4px;
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

.section-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-tip {
  font-size: 13px;
  color: #909399;
  text-align: center;
  margin-top: 8px;
}

.upload-tasks {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.upload-task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.upload-task-name {
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}

.upload-tasks-actions {
  display: flex;
  justify-content: flex-end;
}

.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.search-input {
  flex: 1;
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-results-head {
  font-size: 13px;
  color: #909399;
}

.search-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 16px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.search-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}

.search-item-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.search-item-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.search-item-title {
  font-size: 13px;
  color: #606266;
}

.search-item-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
}

.search-item-foot {
  margin-top: 4px;
  text-align: right;
}

.chunk-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}

.chunks-pagination {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

/* Phase 2 Task C/D: material overview panel */
.overview-panel {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.overview-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.overview-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 14px;
  background: #f5f7fa;
  border-radius: 6px;
  min-width: 100px;
}

.overview-stat.stat-warning {
  background: #fdf6ec;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.overview-stat.stat-warning .stat-value {
  color: #e6a23c;
}

.overview-keywords {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.overview-section-label {
  font-size: 12px;
  color: #909399;
}

.keyword-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.keyword-tag {
  font-size: 12px;
}

.overview-alert {
  margin-top: 4px;
}
</style>
