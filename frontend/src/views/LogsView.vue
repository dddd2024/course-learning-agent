<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import {
  listErrorLogs,
  getErrorLog,
  resolveErrorLog,
  type ErrorLog,
  type ErrorLogCategory,
  type ErrorLogLevel,
  type ErrorLogStatus,
} from '../api/logs'
import { parseApiError } from '../utils/error'
import { formatLocalDateTime } from '../utils/datetime'

const route = useRoute()

const logs = ref<ErrorLog[]>([])
const listLoading = ref(false)

const filterCategory = ref<ErrorLogCategory | ''>('')
const filterLevel = ref<ErrorLogLevel | ''>('')
const filterStatus = ref<ErrorLogStatus | ''>('')
const filterKeyword = ref('')

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<ErrorLog | null>(null)

const categoryOptions: { value: ErrorLogCategory; label: string }[] = [
  { value: 'upload', label: '上传' },
  { value: 'parse', label: '解析' },
  { value: 'agent', label: 'Agent' },
  { value: 'search', label: '搜索' },
  { value: 'system', label: '系统' },
  { value: 'frontend', label: '前端' },
  { value: 'network', label: '网络' },
  { value: 'api', label: '接口' },
]

const levelOptions: { value: ErrorLogLevel; label: string }[] = [
  { value: 'warning', label: '警告' },
  { value: 'error', label: '错误' },
]

const statusOptions: { value: ErrorLogStatus; label: string }[] = [
  { value: 'open', label: '待处理' },
  { value: 'resolved', label: '已解决' },
  { value: 'ignored', label: '已忽略' },
]

const categoryLabel: Record<ErrorLogCategory, string> = {
  upload: '上传',
  parse: '解析',
  agent: 'Agent',
  search: '搜索',
  system: '系统',
  frontend: '前端',
  network: '网络',
  api: '接口',
}

const categoryTagType: Record<ErrorLogCategory, 'info' | 'warning' | 'danger' | 'success' | ''> = {
  upload: 'info',
  parse: 'warning',
  agent: 'danger',
  search: 'success',
  system: '',
  frontend: 'info',
  network: 'warning',
  api: 'danger',
}

const levelTagType: Record<ErrorLogLevel, 'warning' | 'danger'> = {
  warning: 'warning',
  error: 'danger',
}

const statusLabel: Record<ErrorLogStatus, string> = {
  open: '待处理',
  resolved: '已解决',
  ignored: '已忽略',
}

const statusTagType: Record<ErrorLogStatus, 'danger' | 'success' | 'info'> = {
  open: 'danger',
  resolved: 'success',
  ignored: 'info',
}

const presetMaterialId = computed(() => {
  const raw = route.query.material_id
  if (!raw) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
})

function buildListParams() {
  const params: Record<string, unknown> = { page: 1, page_size: 50 }
  if (filterCategory.value) params.category = filterCategory.value
  if (filterLevel.value) params.level = filterLevel.value
  if (filterStatus.value) params.status = filterStatus.value
  if (filterKeyword.value.trim()) params.keyword = filterKeyword.value.trim()
  if (presetMaterialId.value) params.material_id = presetMaterialId.value
  return params
}

async function fetchLogs() {
  listLoading.value = true
  try {
    const { data } = await listErrorLogs(buildListParams())
    logs.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取日志列表失败'))
  } finally {
    listLoading.value = false
  }
}

async function openDetail(row: ErrorLog) {
  drawerVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const { data } = await getErrorLog(row.id)
    detail.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取日志详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function handleResolve(log: ErrorLog, nextStatus: ErrorLogStatus) {
  const actionLabel = nextStatus === 'resolved' ? '解决' : '忽略'
  try {
    await ElMessageBox.confirm(
      `确认将此日志标记为「${actionLabel}」吗？`,
      '操作确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await resolveErrorLog(log.id, nextStatus)
    ElMessage.success(`已标记为「${actionLabel}」`)
    await fetchLogs()
    if (detail.value && detail.value.id === log.id) {
      detail.value = { ...detail.value, status: nextStatus }
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '操作失败'))
  }
}

function handleRefresh() {
  fetchLogs()
}

function handleRowClick(row: ErrorLog) {
  openDetail(row)
}

onMounted(() => {
  if (presetMaterialId.value) {
    filterCategory.value = 'parse'
  }
  fetchLogs()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">日志中心</h2>
      <div class="toolbar-actions">
        <el-select
          v-model="filterCategory"
          placeholder="分类"
          clearable
          style="width: 120px"
          @change="fetchLogs"
        >
          <el-option
            v-for="opt in categoryOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="filterLevel"
          placeholder="级别"
          clearable
          style="width: 120px"
          @change="fetchLogs"
        >
          <el-option
            v-for="opt in levelOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="状态"
          clearable
          style="width: 120px"
          @change="fetchLogs"
        >
          <el-option
            v-for="opt in statusOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-input
          v-model="filterKeyword"
          placeholder="关键词搜索"
          clearable
          style="width: 200px"
          :prefix-icon="Search"
          @clear="fetchLogs"
          @keyup.enter="fetchLogs"
        />
        <el-button type="primary" :icon="Refresh" @click="handleRefresh">
          刷新
        </el-button>
      </div>
    </div>

    <el-card class="section-card" shadow="never">
      <el-table
        v-loading="listLoading"
        :data="logs"
        stripe
        empty-text="暂无异常日志"
        @row-click="handleRowClick"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column label="分类" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="categoryTagType[row.category as ErrorLogCategory]" size="small">
              {{ categoryLabel[row.category as ErrorLogCategory] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="levelTagType[row.level as ErrorLogLevel]" size="small">
              {{ row.level === 'error' ? '错误' : '警告' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status as ErrorLogStatus]" size="small">
              {{ statusLabel[row.status as ErrorLogStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column prop="message" label="消息" min-width="240" show-overflow-tooltip />
        <el-table-column label="重试" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.max_retries">
              {{ row.retry_count }}/{{ row.max_retries }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">
            {{ formatLocalDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'open'"
              type="primary"
              link
              size="small"
              @click.stop="handleResolve(row, 'resolved')"
            >
              标记解决
            </el-button>
            <el-button
              v-if="row.status === 'open'"
              type="info"
              link
              size="small"
              @click.stop="handleResolve(row, 'ignored')"
            >
              忽略
            </el-button>
            <el-button
              type="primary"
              link
              size="small"
              @click.stop="openDetail(row)"
            >
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer
      v-model="drawerVisible"
      title="日志详情"
      direction="rtl"
      size="52%"
      destroy-on-close
    >
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <div class="detail-header">
            <el-tag size="small">#{{ detail.id }}</el-tag>
            <el-tag :type="categoryTagType[detail.category]" size="small">
              {{ categoryLabel[detail.category] }}
            </el-tag>
            <el-tag :type="levelTagType[detail.level]" size="small">
              {{ detail.level === 'error' ? '错误' : '警告' }}
            </el-tag>
            <el-tag :type="statusTagType[detail.status]" size="small">
              {{ statusLabel[detail.status] }}
            </el-tag>
          </div>

          <el-alert
            v-if="detail.message"
            :title="detail.title"
            :description="detail.message"
            :type="detail.level === 'error' ? 'error' : 'warning'"
            :closable="false"
            show-icon
            class="detail-alert"
          />

          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item label="创建时间">
              {{ formatLocalDateTime(detail.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">
              {{ formatLocalDateTime(detail.updated_at) }}
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.course_id" label="课程 ID">
              {{ detail.course_id }}
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.material_id" label="资料 ID">
              {{ detail.material_id }}
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.agent_run_id" label="Agent Run ID">
              {{ detail.agent_run_id }}
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.request_path" label="请求路径">
              {{ detail.request_path }}
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.max_retries" label="重试次数">
              {{ detail.retry_count }} / {{ detail.max_retries }}
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="detail.technical_detail" class="detail-section">
            <h4 class="section-subtitle">技术详情</h4>
            <pre class="data-block">{{ detail.technical_detail }}</pre>
          </div>

          <div v-if="detail.status === 'open'" class="detail-actions">
            <el-button type="primary" @click="handleResolve(detail, 'resolved')">
              标记解决
            </el-button>
            <el-button @click="handleResolve(detail, 'ignored')">
              忽略
            </el-button>
          </div>
        </template>
        <el-empty v-else-if="!detailLoading" description="暂无数据" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
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
  gap: 8px;
}

.title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}

.section-card {
  margin-bottom: 16px;
}

.drawer-body {
  padding: 0 20px 20px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.detail-alert {
  margin-bottom: 16px;
}

.detail-desc {
  margin-bottom: 16px;
}

.detail-section {
  margin-bottom: 16px;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #606266;
}

.data-block {
  background-color: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.detail-actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
}
</style>
