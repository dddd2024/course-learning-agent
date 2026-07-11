<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAgentRuns,
  getAgentRun,
  type AgentRun,
  type AgentRunDetail,
  type AgentRunListParams,
  type AgentStep,
  type FallbackChainStep,
} from '../api/audit'
import { parseApiError } from '../utils/error'

const runs = ref<AgentRun[]>([])
const listLoading = ref(false)

const query = reactive({
  page: 1,
  page_size: 20,
})
const total = ref(0)

const filterRunType = ref<string>('')
const filterStatus = ref<string>('')

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AgentRunDetail | null>(null)

const runTypeOptions = [
  { value: 'course_qa', label: 'course_qa' },
  { value: 'outline', label: 'outline' },
  { value: 'planner', label: 'planner' },
  { value: 'quiz', label: 'quiz' },
  { value: 'concept_compare', label: 'concept_compare' },
  { value: 'material_overview', label: 'material_overview' },
]

// 状态词表与后端 AgentRun.status / AgentStep.status 对齐：
// running / success / degraded / insufficient_evidence / failed / cancelled
const statusOptions = [
  { value: 'running', label: '进行中' },
  { value: 'success', label: '成功' },
  { value: 'degraded', label: '降级' },
  { value: 'insufficient_evidence', label: '证据不足' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const statusTagType: Record<string, 'success' | 'danger' | 'warning' | 'info' | ''> = {
  success: 'success',
  failed: 'danger',
  running: 'warning',
  degraded: 'warning',
  insufficient_evidence: 'warning',
  cancelled: 'info',
}

const statusLabel: Record<string, string> = {
  success: '成功',
  failed: '失败',
  running: '进行中',
  degraded: '降级',
  insufficient_evidence: '证据不足',
  cancelled: '已取消',
}

const evidenceStatusLabel: Record<string, string> = {
  supported: '已验证',
  partial: '部分支持',
  insufficient: '不足',
  not_required: '非必需',
}

const providerLabel: Record<string, string> = {
  mock: 'Mock',
  real: '真实模型',
  user: '用户配置',
}

const providerTagType: Record<string, 'success' | 'warning' | 'info'> = {
  real: 'success',
  user: 'warning',
  mock: 'info',
}

interface RetrievedChunk {
  chunk_id?: number
  score?: number
  snippet?: string
  text?: string
  is_cited?: boolean
  title?: string
  page_no?: number | null
}

function normalizeChunk(value: unknown): RetrievedChunk {
  if (typeof value === 'string') return { snippet: value }
  if (value && typeof value === 'object') return value as RetrievedChunk
  return { snippet: String(value ?? '') }
}

function extractChunks(step: AgentStep): RetrievedChunk[] {
  const out = step.output_data
  if (!out) return []
  if (Array.isArray(out)) return out.map(normalizeChunk)
  if (typeof out === 'object') {
    const obj = out as Record<string, unknown>
    // T0-1: 真实 chat retrieve step 写入 { total, items } 结构，
    // 旧 seed 写入 { chunks } 结构，两种都要支持。
    if (Array.isArray(obj.items)) return obj.items.map(normalizeChunk)
    if (Array.isArray(obj.chunks)) return obj.chunks.map(normalizeChunk)
  }
  return []
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
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${day} ${hh}:${mm}:${ss}`
}

function formatData(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function stepStatus(status: string): 'finish' | 'error' | 'process' | 'wait' {
  if (status === 'success') return 'finish'
  if (status === 'failed') return 'error'
  if (status === 'running') return 'process'
  return 'wait'
}

function providerModelDiff(row: AgentRun): boolean {
  return (
    !!row.requested_provider &&
    !!row.actual_provider &&
    row.requested_provider !== row.actual_provider
  ) || (
    !!row.requested_model &&
    !!row.actual_model &&
    row.requested_model !== row.actual_model
  )
}

function fallbackChainSteps(row: AgentRun): FallbackChainStep[] {
  if (!row.fallback_chain) return []
  if (Array.isArray(row.fallback_chain)) return row.fallback_chain as FallbackChainStep[]
  return []
}

const sortedSteps = computed<AgentStep[]>(() => {
  if (!detail.value) return []
  return [...detail.value.steps].sort((a, b) => a.step_index - b.step_index)
})

function buildListParams(): AgentRunListParams {
  const params: AgentRunListParams = {
    limit: query.page_size,
    offset: (query.page - 1) * query.page_size,
  }
  if (filterRunType.value) params.run_type = filterRunType.value
  if (filterStatus.value) params.status = filterStatus.value
  return params
}

async function fetchRuns() {
  listLoading.value = true
  try {
    const { data } = await getAgentRuns(buildListParams())
    runs.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取运行列表失败'))
  } finally {
    listLoading.value = false
  }
}

async function openDetail(row: AgentRun) {
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    const { data } = await getAgentRun(row.id)
    detail.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取运行详情失败'))
  } finally {
    detailLoading.value = false
  }
}

function handleRefresh() {
  fetchRuns()
}

function handlePageSizeChange() {
  query.page = 1
  fetchRuns()
}

function handleFilterChange() {
  query.page = 1
  fetchRuns()
}

function handleRowClick(row: AgentRun) {
  openDetail(row)
}

onMounted(() => {
  fetchRuns()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2 class="title">Agent 审计</h2>
      <div class="toolbar-actions">
        <el-select
          v-model="filterRunType"
          placeholder="运行类型"
          clearable
          style="width: 160px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="opt in runTypeOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="filterStatus"
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
        <el-button type="primary" @click="handleRefresh">刷新</el-button>
      </div>
    </div>

    <el-card class="section-card" shadow="never">
      <el-table
        :data="runs"
        v-loading="listLoading"
        stripe
        empty-text="暂无运行记录"
        @row-click="handleRowClick"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column prop="run_type" label="运行类型" width="120" />
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status] || 'info'" size="small">
              {{ statusLabel[row.status] || row.status }}
            </el-tag>
            <el-tag
              v-if="row.fallback_used"
              type="warning"
              size="small"
              style="margin-left: 4px"
            >
              降级
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="110" align="center">
          <template #default="{ row }">
            {{ formatDuration(row.duration_ms) }}
          </template>
        </el-table-column>
        <el-table-column label="开始时间" min-width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="model_name" label="模型" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.model_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              v-if="row.provider"
              :type="providerTagType[row.provider] || 'info'"
              size="small"
            >
              {{ providerLabel[row.provider] || row.provider }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="prompt_version" label="Prompt 版本" width="130" align="center">
          <template #default="{ row }">
            {{ row.prompt_version || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click.stop="openDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pagination-bar"
        @current-change="fetchRuns"
        @size-change="handlePageSizeChange"
      />
    </el-card>

    <el-drawer
      v-model="drawerVisible"
      title="运行详情"
      direction="rtl"
      size="56%"
      destroy-on-close
    >
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <div class="detail-header">
            <span class="detail-id">#{{ detail.id }}</span>
            <el-tag :type="statusTagType[detail.status] || 'info'" size="small">
              {{ statusLabel[detail.status] || detail.status }}
            </el-tag>
            <el-tag type="info" size="small">{{ detail.run_type }}</el-tag>
          </div>

          <el-alert
            v-if="detail.error_message"
            class="detail-alert"
            :title="detail.error_message"
            type="error"
            :closable="false"
            show-icon
          />

          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item label="开始时间">
              {{ formatDateTime(detail.started_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="结束时间">
              {{ formatDateTime(detail.finished_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="耗时">
              {{ formatDuration(detail.duration_ms) }}
            </el-descriptions-item>
            <el-descriptions-item label="模型">
              {{ detail.model_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Prompt 版本">
              {{ detail.prompt_version || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ formatDateTime(detail.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="请求 Provider">
              {{ detail.requested_provider || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="实际 Provider">
              <span v-if="detail.actual_provider">
                {{ detail.actual_provider }}
                <el-tag
                  v-if="providerModelDiff(detail)"
                  type="warning"
                  size="small"
                  style="margin-left: 4px"
                >
                  与请求不一致
                </el-tag>
              </span>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="请求模型">
              {{ detail.requested_model || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="实际模型">
              {{ detail.actual_model || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="证据状态">
              <el-tag
                v-if="detail.evidence_status"
                :type="detail.evidence_status === 'supported' ? 'success' : detail.evidence_status === 'insufficient' ? 'danger' : 'warning'"
                size="small"
              >
                {{ evidenceStatusLabel[detail.evidence_status] || detail.evidence_status }}
              </el-tag>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="Fallback">
              <el-tag v-if="detail.fallback_used" type="warning" size="small">是</el-tag>
              <span v-else>否</span>
              <span v-if="detail.fallback_reason" style="margin-left: 8px; color: #909399; font-size: 12px">
                {{ detail.fallback_reason }}
              </span>
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="fallbackChainSteps(detail).length > 0" class="detail-section">
            <div class="section-subtitle">Fallback Chain</div>
            <el-timeline>
              <el-timeline-item
                v-for="(step, i) in fallbackChainSteps(detail)"
                :key="i"
                :type="step.status === 'success' ? 'success' : step.status === 'failed' ? 'danger' : 'warning'"
                placement="top"
              >
                <div class="fallback-step">
                  <span class="fallback-provider">{{ step.provider || '-' }}</span>
                  <span v-if="step.model" class="fallback-model">{{ step.model }}</span>
                  <el-tag
                    :type="step.status === 'success' ? 'success' : step.status === 'failed' ? 'danger' : 'warning'"
                    size="small"
                  >
                    {{ step.status || '-' }}
                  </el-tag>
                  <span v-if="step.reason" class="fallback-reason">{{ step.reason }}</span>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>

          <div class="detail-section">
            <div class="section-subtitle">输入摘要</div>
            <pre class="data-block">{{ formatData(detail.input_summary) }}</pre>
          </div>

          <div class="detail-section">
            <div class="section-subtitle">输出摘要</div>
            <pre class="data-block">{{ formatData(detail.output_summary) }}</pre>
          </div>

          <div v-if="sortedSteps.length > 0" class="detail-section">
            <div class="section-subtitle">步骤进度</div>
            <el-steps :active="sortedSteps.length" finish-status="success" align-center>
              <el-step
                v-for="step in sortedSteps"
                :key="step.id"
                :title="step.step_name"
                :status="stepStatus(step.status)"
              />
            </el-steps>
          </div>

          <div v-if="sortedSteps.length > 0" class="detail-section">
            <div class="section-subtitle">步骤明细</div>
            <el-timeline>
              <el-timeline-item
                v-for="step in sortedSteps"
                :key="step.id"
                :timestamp="formatDuration(step.duration_ms)"
                placement="top"
                :type="
                  step.status === 'success'
                    ? 'success'
                    : step.status === 'failed'
                    ? 'danger'
                    : 'warning'
                "
              >
                <div class="step-card">
                  <div class="step-head">
                    <span class="step-order">#{{ step.step_index }}</span>
                    <span class="step-name">{{ step.step_name }}</span>
                    <el-tag
                      :type="statusTagType[step.status] || 'info'"
                      size="small"
                    >
                      {{ statusLabel[step.status] || step.status }}
                    </el-tag>
                  </div>
                  <el-alert
                    v-if="step.error_message"
                    class="step-alert"
                    :title="step.error_message"
                    type="error"
                    :closable="false"
                    show-icon
                  />
                  <div class="step-field">
                    <span class="step-field-label">输入：</span>
                    <pre class="data-block">{{ formatData(step.input_data) }}</pre>
                  </div>
                  <div class="step-field">
                    <span class="step-field-label">输出：</span>
                    <pre class="data-block">{{ formatData(step.output_data) }}</pre>
                  </div>
                  <div v-if="extractChunks(step).length > 0" class="step-field">
                    <span class="step-field-label">检索证据：</span>
                    <div class="chunks-list">
                      <div
                        v-for="(c, i) in extractChunks(step)"
                        :key="i"
                        class="chunk-card"
                      >
                        <div class="chunk-head">
                          <span class="chunk-id">#{{ c.chunk_id ?? i + 1 }}</span>
                          <span v-if="c.score !== undefined" class="chunk-score">
                            score: {{ Number(c.score).toFixed(2) }}
                          </span>
                          <span v-if="c.title" class="chunk-title" :title="c.title">
                            {{ c.title }}
                          </span>
                          <span v-if="c.page_no !== undefined && c.page_no !== null" class="chunk-page">
                            P{{ c.page_no }}
                          </span>
                          <el-tag
                            v-if="c.is_cited !== undefined"
                            size="small"
                            :type="c.is_cited ? 'success' : 'info'"
                          >
                            {{ c.is_cited ? '已引用' : '未引用' }}
                          </el-tag>
                        </div>
                        <div class="chunk-snippet">
                          {{ c.snippet || c.text || '-' }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>

          <el-empty
            v-else
            description="暂无步骤记录"
          />
        </template>
        <el-empty
          v-else-if="!detailLoading"
          description="暂无数据"
        />
      </div>
    </el-drawer>
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
  flex-wrap: wrap;
  gap: 12px;
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

.pagination-bar {
  margin-top: 16px;
  justify-content: flex-end;
}

.drawer-body {
  padding: 0 4px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.detail-id {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.detail-alert {
  margin-bottom: 16px;
}

.detail-desc {
  margin-bottom: 20px;
}

.detail-section {
  margin-bottom: 24px;
}

.section-subtitle {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.data-block {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  margin: 0;
  font-size: 13px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}

.step-card {
  padding: 4px 0;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.step-order {
  font-size: 13px;
  color: #909399;
}

.step-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.step-alert {
  margin-bottom: 8px;
}

.step-field {
  margin-bottom: 8px;
}

.step-field-label {
  font-size: 13px;
  color: #606266;
  display: block;
  margin-bottom: 4px;
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chunk-card {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  padding: 8px 10px;
}

.chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
  font-size: 12px;
}

.chunk-id {
  font-weight: 600;
  color: #303133;
}

.chunk-score {
  color: #e6a23c;
}

.chunk-title {
  color: #606266;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-page {
  color: #909399;
}

.chunk-snippet {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.fallback-step {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.fallback-provider {
  font-weight: 600;
  color: #303133;
  font-size: 13px;
}

.fallback-model {
  color: #606266;
  font-size: 13px;
}

.fallback-reason {
  color: #909399;
  font-size: 12px;
}
</style>
