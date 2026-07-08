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
  type FrontendErrorReportPayload,
} from '../api/logs'
import { parseApiError } from '../utils/error'
import { formatLocalDateTime } from '../utils/datetime'
import {
  checkBackendHealth,
  checkBackendHealthByHost,
  type BackendHealth,
  type HostHealthResult,
} from '../api/health'
import {
  API_BASE_URL,
  DIAG_HOSTS,
  BACKEND_LOG_PATH,
  START_SCRIPT_PATH,
} from '../config/api'
import {
  readPendingQueue,
  flushPendingErrorReports,
} from '../utils/errorReport'

const route = useRoute()

const logs = ref<ErrorLog[]>([])
const listLoading = ref(false)

// Redo Task B: backend connection + load state so the empty table no
// longer lies ("暂无异常日志") when the backend is actually down.
type ConnState = 'unknown' | 'ok' | 'unreachable' | 'auth_failed'
const backendConn = ref<ConnState>('unknown')
const backendHealth = ref<BackendHealth | null>(null)
const healthCheckedAt = ref<string | null>(null)
const loadError = ref<string | null>(null)

// Redo Task B: local pending reports (backend-unreachable backlog).
const pendingLocalReports = ref<FrontendErrorReportPayload[]>([])
const flushing = ref(false)

// One-click-launch fix D1: launch-chain diagnostics — probe both 127.0.0.1
// and localhost so the user can tell address-resolution failure from a
// backend that is genuinely not running.
const diagRunning = ref(false)
const hostResults = ref<HostHealthResult[]>([])
const diagCheckedAt = ref<string | null>(null)

// D4: dedupe pending reports by signature for display so the panel never
// shows a wall of identical /logs errors even if the queue grew before
// the dedupe fix.
const pendingDeduped = computed(() => {
  const seen = new Set<string>()
  const out: FrontendErrorReportPayload[] = []
  for (const p of pendingLocalReports.value) {
    const sig = `${p.title}|${p.request_path || ''}|${p.message}`
    if (seen.has(sig)) continue
    seen.add(sig)
    out.push(p)
  }
  return out
})

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

// Redo Task B/D: empty-text must reflect WHY the list is empty. "暂无异常日志"
// only applies when the backend is reachable and returned an empty page.
const emptyText = computed(() => {
  if (backendConn.value === 'unreachable') {
    return '后端不可达，无法加载服务端日志'
  }
  if (backendConn.value === 'auth_failed') {
    return '登录已失效，请重新登录后再查看日志'
  }
  if (loadError.value) {
    return '日志加载失败，请刷新重试'
  }
  return '暂无异常日志'
})

async function checkHealth() {
  try {
    const h = await checkBackendHealth()
    backendHealth.value = h
    healthCheckedAt.value = new Date().toLocaleTimeString()
    // Only treat our own backend as "ok"; a different app on 8000 is a misconfig.
    backendConn.value = h.app === 'course-learning-agent' ? 'ok' : 'unreachable'
  } catch {
    backendHealth.value = null
    healthCheckedAt.value = new Date().toLocaleTimeString()
    backendConn.value = 'unreachable'
  }
}

// One-click-launch fix D1: probe both 127.0.0.1 and localhost so the user
// can distinguish "localhost resolves to IPv6 ::1 but backend is on IPv4"
// from "backend is genuinely not running". Uses checkBackendHealthByHost
// which never throws and never triggers the error-report interceptor.
async function runDiagnostics() {
  diagRunning.value = true
  try {
    const results = await Promise.all(
      DIAG_HOSTS.map((host) => checkBackendHealthByHost(host)),
    )
    hostResults.value = results
    diagCheckedAt.value = new Date().toLocaleTimeString()
  } finally {
    diagRunning.value = false
  }
}

// D1 helper: label the address-resolution verdict from hostResults.
const diagVerdict = computed(() => {
  if (hostResults.value.length === 0) return ''
  const r127 = hostResults.value.find((r) => r.host === '127.0.0.1')
  const rLocal = hostResults.value.find((r) => r.host === 'localhost')
  if (r127 && rLocal) {
    if (r127.ok && !rLocal.ok) {
      return '127.0.0.1 可达但 localhost 不可达 — 这是地址解析问题（localhost 可能解析到 IPv6 ::1）。建议：前端已默认使用 127.0.0.1，请刷新页面。'
    }
    if (!r127.ok && rLocal.ok) {
      return 'localhost 可达但 127.0.0.1 不可达 — 环境异常或代理/hosts 问题。'
    }
    if (r127.ok && rLocal.ok) {
      return '两个地址均可达 — 后端健康，问题可能在前端缓存或登录态。'
    }
    return '两个地址均不可达 — 后端未启动或已崩溃。请运行 start_windows.ps1 并查看 backend.log。'
  }
  return ''
})

async function fetchLogs() {
  listLoading.value = true
  loadError.value = null
  try {
    const { data } = await listErrorLogs(buildListParams())
    logs.value = data.items
    backendConn.value = 'ok'
  } catch (err) {
    const status = (err as { response?: { status?: number } }).response?.status
    if (status === 401) {
      backendConn.value = 'auth_failed'
    } else if (status === undefined) {
      backendConn.value = 'unreachable'
    } else {
      backendConn.value = 'ok'
    }
    loadError.value = parseApiError(err, '获取日志列表失败')
    // Don't toast when the backend is down — the banner explains it.
    if (backendConn.value === 'ok') {
      ElMessage.error(loadError.value)
    }
  } finally {
    listLoading.value = false
  }
}

function refreshPending() {
  pendingLocalReports.value = readPendingQueue()
}

async function handleReconnectAndFlush() {
  flushing.value = true
  try {
    await checkHealth()
    if (backendConn.value !== 'ok') {
      ElMessage.warning('后端仍不可达，本地待上报日志已保留，请稍后重试')
      return
    }
    await flushPendingErrorReports()
    refreshPending()
    if (pendingLocalReports.value.length === 0) {
      ElMessage.success('本地待上报日志已补发至日志中心')
      await fetchLogs()
    } else {
      ElMessage.warning('部分日志仍未能补发，请确认登录状态后重试')
    }
  } finally {
    flushing.value = false
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

async function handleRefresh() {
  await checkHealth()
  await fetchLogs()
  refreshPending()
  // D1: when the backend looks unreachable, auto-run the dual-host
  // diagnostics so the user sees WHY without an extra click.
  if (backendConn.value === 'unreachable') {
    runDiagnostics()
  }
}

function handleRowClick(row: ErrorLog) {
  openDetail(row)
}

onMounted(() => {
  if (presetMaterialId.value) {
    filterCategory.value = 'parse'
  }
  checkHealth()
  fetchLogs()
  refreshPending()
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

    <!-- Redo Task D: backend service status banner -->
    <el-alert
      v-if="backendConn === 'unreachable'"
      type="error"
      :closable="false"
      show-icon
      title="后端服务不可达"
      class="status-banner"
    >
      <div>
        无法连接后端服务。当前请求地址：<code>{{ API_BASE_URL }}</code>
      </div>
      <div style="margin-top: 6px">
        请确认后端已启动：运行 <code>{{ START_SCRIPT_PATH }}</code> 或
        <code>uvicorn app.main:app --reload --host 127.0.0.1 --port 8000</code>。
      </div>
      <div style="margin-top: 6px">
        启动失败时请查看日志：<code>{{ BACKEND_LOG_PATH }}</code>
      </div>
      <div style="margin-top: 6px">
        服务端日志无法加载，但前端错误已保存到下方"本地待上报日志"，后端恢复并登录后可补发。
      </div>
    </el-alert>
    <el-alert
      v-else-if="backendConn === 'auth_failed'"
      type="warning"
      :closable="false"
      show-icon
      title="登录已失效"
      class="status-banner"
    >
      请重新登录后再查看服务端日志。本地待上报日志已保留，登录后可补发。
    </el-alert>
    <el-alert
      v-else-if="backendConn === 'ok' && backendHealth"
      type="success"
      :closable="false"
      show-icon
      :title="`后端服务正常 · ${backendHealth.app} v${backendHealth.version}`"
      class="status-banner"
    >
      最近检查时间：{{ healthCheckedAt }} · 请求地址：{{ API_BASE_URL }}
    </el-alert>

    <!-- One-click-launch fix D1: launch-chain diagnostics panel -->
    <el-card class="diag-card" shadow="never">
      <template #header>
        <div class="diag-header">
          <span class="diag-title">启动链路诊断</span>
          <el-button
            size="small"
            :loading="diagRunning"
            @click="runDiagnostics"
          >
            重新诊断
          </el-button>
        </div>
      </template>
      <div class="diag-row">
        <span class="diag-label">当前 API 地址：</span>
        <code>{{ API_BASE_URL }}</code>
      </div>
      <div v-for="r in hostResults" :key="r.host" class="diag-row">
        <span class="diag-label">{{ r.host }}：</span>
        <el-tag
          :type="r.ok ? 'success' : 'danger'"
          size="small"
          style="margin-right: 8px"
        >
          {{ r.ok ? '可达' : '不可达' }}
        </el-tag>
        <span v-if="r.ok && r.health" class="diag-detail">
          {{ r.health.app }} v{{ r.health.version }}
        </span>
        <span v-else class="diag-detail">{{ r.error }}</span>
      </div>
      <div v-if="diagCheckedAt" class="diag-row diag-time">
        最近诊断时间：{{ diagCheckedAt }}
      </div>
      <el-alert
        v-if="diagVerdict"
        type="info"
        :closable="false"
        show-icon
        class="diag-verdict"
      >
        {{ diagVerdict }}
      </el-alert>
    </el-card>

    <!-- Redo Task B: local pending reports panel -->
    <el-card
      v-if="pendingLocalReports.length > 0"
      class="pending-card"
      shadow="never"
    >
      <template #header>
        <div class="pending-header">
          <span class="pending-title">
            本地待上报日志（{{ pendingLocalReports.length }} 条，去重后 {{ pendingDeduped.length }} 条）
          </span>
          <el-button
            type="primary"
            size="small"
            :loading="flushing"
            @click="handleReconnectAndFlush"
          >
            重新连接并补发
          </el-button>
        </div>
      </template>
      <el-table :data="pendingDeduped" size="small" stripe>
        <el-table-column label="分类" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.category === 'network' ? 'warning' : 'danger'">
              {{ row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
        <el-table-column prop="message" label="消息" min-width="220" show-overflow-tooltip />
        <el-table-column label="请求路径" width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.request_path || '-' }}
          </template>
        </el-table-column>
      </el-table>
      <div class="pending-hint">
        这些错误在后端不可达时产生，已暂存在本地（sessionStorage）。点击"重新连接并补发"将它们写入服务端日志中心。
      </div>
    </el-card>

    <el-card class="section-card" shadow="never">
      <el-table
        v-loading="listLoading"
        :data="logs"
        stripe
        :empty-text="emptyText"
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

.status-banner {
  margin-bottom: 16px;
}

/* One-click-launch fix D1: diagnostics panel */
.diag-card {
  margin-bottom: 16px;
  border-left: 3px solid #409eff;
}

.diag-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.diag-title {
  font-size: 14px;
  font-weight: 600;
  color: #409eff;
}

.diag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 13px;
}

.diag-label {
  font-weight: 600;
  color: #606266;
  min-width: 120px;
}

.diag-detail {
  color: #909399;
  font-size: 12px;
}

.diag-time {
  color: #c0c4cc;
  font-size: 12px;
  margin-top: 4px;
}

.diag-verdict {
  margin-top: 8px;
}

.pending-card {
  margin-bottom: 16px;
  border-left: 3px solid #e6a23c;
}

.pending-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pending-title {
  font-size: 14px;
  font-weight: 600;
  color: #e6a23c;
}

.pending-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
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
