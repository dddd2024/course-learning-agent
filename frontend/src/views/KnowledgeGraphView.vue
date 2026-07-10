<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { Network, DataSet } from 'vis-network/standalone'
import 'vis-network/styles/vis-network.css'
import {
  rebuildGraph,
  getGraph,
  getNodeDetail,
  confirmEdge,
  rejectEdge,
  compareNodes,
  type GraphNode,
  type GraphEdge,
  type NodeDetail,
  type CompareReport,
} from '../api/conceptGraph'
import { listCourses, type Course } from '../api/course'
import { parseApiError } from '../utils/error'

const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const loading = ref(false)
const allCourses = ref<Course[]>([])

const selectedNode = ref<NodeDetail | null>(null)
const selectedEdge = ref<GraphEdge | null>(null)
const detailDrawerVisible = ref(false)
const legendCollapsed = ref(false)
const compareDrawerVisible = ref(false)
const compareReport = ref<CompareReport | null>(null)
const compareLoading = ref(false)
const compareUserFocus = ref('concept')
const userFocusOptions = [
  { label: '概念理解', value: 'concept' },
  { label: '考试重点', value: 'exam' },
  { label: '迁移应用', value: 'transfer' },
]

// Filters
const filterCourseId = ref('')
const filterRelationType = ref('')
const filterStatus = ref('')

const relationColors: Record<string, string> = {
  similar_to: '#67C23A',
  contrast_with: '#E6A23C',
  prerequisite_of: '#409EFF',
  applies_to: '#909399',
  same_name_different_meaning: '#F56C6C',
  confused_with: '#9C27B0',
  parent_of: '#00BCD4',
}

const relationLabels: Record<string, string> = {
  similar_to: '相似',
  contrast_with: '对比',
  prerequisite_of: '前置',
  applies_to: '迁移应用',
  same_name_different_meaning: '同名异义',
  confused_with: '易混',
  parent_of: '上下位',
}

const statusLabels: Record<string, string> = {
  candidate: '候选',
  confirmed: '已确认',
  rejected: '已拒绝',
}

const courseOptions = computed(() => allCourses.value)

const courseColors = computed(() => {
  const colors = [
    '#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16',
    '#E8684A', '#6DC8EC', '#9270CA', '#FF9D4D',
  ]
  const m = new Map<number, string>()
  const courseIds = new Set(nodes.value.map(n => n.course_id))
  Array.from(courseIds).forEach((cid, i) => {
    m.set(cid, colors[i % colors.length])
  })
  return m
})

// --- vis-network instance ---
const graphContainer = ref<HTMLElement | null>(null)
let network: Network | null = null
let resizeObserver: ResizeObserver | null = null
const nodesDataSet = new DataSet<any>([])
const edgesDataSet = new DataSet<any>([])

function buildVisData() {
  const visNodes = nodes.value.map(n => {
    const color = courseColors.value.get(n.course_id) || '#909399'
    const isWeak = n.weak_point_score > 0
    const size = 18 + Math.max(0, (n.importance || 3) - 3) * 4 + (isWeak ? 6 : 0)
    return {
      id: n.id,
      label: cleanNodeLabel(n.title),
      title: `${n.title}\n课程: ${allCourses.value.find(c => c.id === n.course_id)?.name || '#' + n.course_id}\n重要度: ${n.importance}${isWeak ? '\n⚠ 薄弱点' : ''}`,
      shape: 'dot',
      size: size,
      color: {
        background: color,
        border: isWeak ? '#F56C6C' : color,
        highlight: { background: color, border: '#303133' },
        hover: { background: color, border: '#303133' },
      },
      font: {
        size: 13,
        color: '#303133',
        face: 'system-ui, -apple-system, sans-serif',
        multi: 'html',
      },
      _data: n,
    }
  })

  const visEdges = edges.value.map(e => ({
    id: e.id,
    from: e.source_node_id,
    to: e.target_node_id,
    color: {
      color: relationColors[e.relation_type] || '#C0C4CC',
      highlight: relationColors[e.relation_type] || '#C0C4CC',
      hover: relationColors[e.relation_type] || '#C0C4CC',
    },
    width: e.status === 'confirmed' ? 2.5 : 1.5,
    dashes: e.status === 'candidate' ? [6, 4] : false,
    label: relationLabels[e.relation_type] || '',
    font: {
      size: 10,
      color: '#909399',
      strokeWidth: 0,
      align: 'middle',
    },
    smooth: { enabled: true, type: 'continuous', roundness: 0.3 },
    _data: e,
  }))

  nodesDataSet.clear()
  nodesDataSet.add(visNodes)
  edgesDataSet.clear()
  edgesDataSet.add(visEdges)
}

function initNetwork() {
  if (!graphContainer.value) return

  const options = {
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -60,
        centralGravity: 0.01,
        springLength: 120,
        springConstant: 0.05,
        damping: 0.4,
        avoidOverlap: 0.5,
      },
      stabilization: {
        enabled: true,
        iterations: 200,
        updateInterval: 25,
      },
      timestep: 0.35,
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      navigationButtons: true,
      keyboard: true,
      multiselect: false,
      zoomView: true,
      dragView: true,
      dragNodes: true,
    },
    layout: {
      improvedLayout: true,
    },
    nodes: {
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: 'rgba(0,0,0,0.1)',
        size: 6,
        x: 2,
        y: 4,
      },
      scaling: {
        min: 10,
        max: 35,
      },
    },
    edges: {
      smooth: {
        enabled: true,
        type: 'continuous',
        roundness: 0.3,
      },
      selectionWidth: 3,
    },
  }

  network = new Network(
    graphContainer.value,
    { nodes: nodesDataSet, edges: edgesDataSet },
    options,
  )

  network.on('click', (params: any) => {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0]
      const node = nodes.value.find(n => n.id === nodeId)
      if (node) handleNodeClick(node)
    } else if (params.edges.length > 0) {
      const edgeId = params.edges[0]
      const edge = edges.value.find(e => e.id === edgeId)
      if (edge) handleEdgeClick(edge)
    } else {
      selectedNode.value = null
      selectedEdge.value = null
      detailDrawerVisible.value = false
    }
  })

  network.on('stabilizationIterationsDone', () => {
    network?.setOptions({ physics: { enabled: false } })
    network?.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } })
  })

  // Observe container size changes so vis-network redraws when the layout
  // changes (e.g. sidebar collapse) without a window resize event.
  if (graphContainer.value) {
    resizeObserver = new ResizeObserver(() => {
      if (network && graphContainer.value) {
        network.redraw()
      }
    })
    resizeObserver.observe(graphContainer.value)
  }
}

function destroyNetwork() {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (network) {
    network.destroy()
    network = null
  }
}

async function fetchGraph() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (filterCourseId.value) params.course_ids = filterCourseId.value
    if (filterRelationType.value) params.relation_type = filterRelationType.value
    if (filterStatus.value) params.status = filterStatus.value
    const { data } = await getGraph(params)
    nodes.value = data.nodes
    edges.value = data.edges
    await nextTick()
    buildVisData()
    if (!network) {
      // Wait one animation frame to guarantee the browser has performed
      // layout so the container has real, non-zero dimensions before
      // vis-network measures it.  Without this the canvas can be
      // created at 0×0 and nothing is rendered.
      await new Promise(resolve => requestAnimationFrame(() => resolve(null)))
      initNetwork()
    } else {
      // Network already exists — re-enable physics and re-stabilize so
      // the new data settles into a good layout, then fit the view.
      network.setOptions({ physics: { enabled: true } })
      network.stabilize()
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取图谱失败'))
  } finally {
    loading.value = false
  }
}

async function handleRebuild() {
  try {
    await ElMessageBox.confirm(
      '重建图谱将重新分析所有知识点关系，可能需要较长时间。确定继续吗？',
      '重建确认',
      { type: 'warning', confirmButtonText: '重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    const { data } = await rebuildGraph()
    await fetchGraph()
    ElMessage.success(
      `图谱重建完成：${data.nodes_count} 节点 / ${data.edges_count} 候选边`,
    )
  } catch (err) {
    ElMessage.error(parseApiError(err, '重建图谱失败'))
  } finally {
    loading.value = false
  }
}

async function handleNodeClick(node: GraphNode) {
  selectedEdge.value = null
  detailDrawerVisible.value = true
  try {
    const { data } = await getNodeDetail(node.id)
    selectedNode.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取节点详情失败'))
  }
}

function handleEdgeClick(edge: GraphEdge) {
  selectedNode.value = null
  selectedEdge.value = edge
  detailDrawerVisible.value = true
}

async function handleConfirm() {
  if (!selectedEdge.value) return
  try {
    await confirmEdge(selectedEdge.value.id)
    selectedEdge.value.status = 'confirmed'
    ElMessage.success('已确认该关系')
  } catch (err) {
    ElMessage.error(parseApiError(err, '确认失败'))
  }
}

async function handleReject() {
  if (!selectedEdge.value) return
  try {
    await rejectEdge(selectedEdge.value.id)
    selectedEdge.value.status = 'rejected'
    ElMessage.success('已拒绝该关系')
  } catch (err) {
    ElMessage.error(parseApiError(err, '拒绝失败'))
  }
}

async function handleCompare() {
  if (!selectedEdge.value) return
  compareLoading.value = true
  compareDrawerVisible.value = true
  compareReport.value = null
  try {
    const { data } = await compareNodes(
      selectedEdge.value.source_node_id,
      selectedEdge.value.target_node_id,
      selectedEdge.value.id,
      compareUserFocus.value,
    )
    compareReport.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成对比报告失败'))
  } finally {
    compareLoading.value = false
  }
}

function fitGraph() {
  network?.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } })
}

function cleanNodeLabel(title: string): string {
  if (!title) return ''
  let result = title.replace(/[□☐◆■►●○▪▫▶▷◇★☆▼▽▲△]/g, '')
  result = result.replace(/\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?/g, '')
  result = result.replace(/\b\d{4}\b/g, '')
  result = result.replace(/第\d+页|P\d+|\[[A-Za-z]+\]/g, '')
  result = result.replace(/^第[一二三四五六七八九十\d]+章\s*/g, '')
  result = result.replace(/^[\d.]+\s+/g, '')
  result = result.replace(/\s+/g, ' ').trim()
  if (!result) return title
  // Truncate long labels for display
  if (result.length > 12) return result.substring(0, 11) + '…'
  return result
}

function nodeTitle(id: number): string {
  const n = nodes.value.find((x) => x.id === id)
  return n ? n.title : `#${id}`
}

watch([filterCourseId, filterRelationType, filterStatus], () => {
  fetchGraph()
})

onMounted(async () => {
  try {
    const { data } = await listCourses({ page: 1, page_size: 100 })
    allCourses.value = data.items
  } catch {
    // 静默失败
  }
  await fetchGraph()
})

onBeforeUnmount(() => {
  destroyNetwork()
})
</script>

<template>
  <div class="kg-page">
    <!-- Top toolbar: compact filters + actions -->
    <div class="kg-toolbar">
      <div class="kg-filters">
        <el-select
          v-model="filterCourseId"
          placeholder="全部课程"
          clearable
          size="small"
          style="width: 150px"
        >
          <el-option
            v-for="c in courseOptions"
            :key="c.id"
            :label="c.name"
            :value="String(c.id)"
          />
        </el-select>
        <el-select
          v-model="filterRelationType"
          placeholder="全部关系"
          clearable
          size="small"
          style="width: 120px"
        >
          <el-option
            v-for="(label, key) in relationLabels"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="全部状态"
          clearable
          size="small"
          style="width: 120px"
        >
          <el-option
            v-for="(label, key) in statusLabels"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </div>
      <div class="kg-actions">
        <span v-if="nodes.length > 0" class="kg-stats">{{ nodes.length }} 节点 · {{ edges.length }} 关系</span>
        <el-button size="small" @click="fitGraph">适应视图</el-button>
        <el-button
          type="primary"
          size="small"
          :loading="loading"
          @click="handleRebuild"
        >
          重建图谱
        </el-button>
      </div>
    </div>

    <!-- Main graph canvas -->
    <div class="kg-canvas-wrap" v-loading="loading">
      <div
        ref="graphContainer"
        class="graph-canvas"
      ></div>
      <div v-if="!nodes.length && !loading" class="empty-tip-overlay">
        <el-empty description="暂无图谱数据">
          <el-button type="primary" @click="handleRebuild">重建图谱</el-button>
        </el-empty>
      </div>

      <!-- Floating legend (collapsible) -->
      <div v-if="nodes.length > 0" class="kg-legend" :class="{ 'kg-legend--collapsed': legendCollapsed }">
        <div class="legend-header" @click="legendCollapsed = !legendCollapsed">
          <span>图例</span>
          <el-icon size="12"><ArrowDown v-if="!legendCollapsed" /><ArrowRight v-else /></el-icon>
        </div>
        <div v-show="!legendCollapsed" class="legend-body">
          <div class="legend-section">
            <div class="legend-subtitle">课程</div>
            <div
              v-for="[cid, color] in Array.from(courseColors.entries())"
              :key="cid"
              class="legend-item"
            >
              <span class="legend-dot" :style="{ background: color }" />
              <span>{{ allCourses.find((c) => c.id === cid)?.name || `课程 #${cid}` }}</span>
            </div>
          </div>
          <div class="legend-section">
            <div class="legend-subtitle">关系</div>
            <div
              v-for="(color, key) in relationColors"
              :key="key"
              class="legend-item"
            >
              <span class="legend-line" :style="{ background: color }" />
              <span>{{ relationLabels[key] || key }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Detail drawer -->
    <el-drawer
      v-model="detailDrawerVisible"
      :title="selectedNode ? '节点详情' : '关系详情'"
      size="360px"
      direction="rtl"
    >
      <div v-if="selectedNode" class="detail-section">
        <div class="detail-row">
          <span class="detail-label">标题</span>
          <span class="detail-value">{{ selectedNode?.title }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">课程</span>
          <span class="detail-value">{{
            allCourses.find(c => c.id === selectedNode?.course_id)?.name || '#' + selectedNode?.course_id
          }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">重要度</span>
          <span class="detail-value">{{ selectedNode?.importance }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">薄弱点</span>
          <span class="detail-value">
            {{ (selectedNode?.weak_point_score ?? 0) > 0 ? '是' : '否' }}
          </span>
        </div>
        <div v-if="selectedNode?.summary" class="detail-block">
          <div class="detail-label">摘要</div>
          <div class="detail-text">{{ selectedNode?.summary }}</div>
        </div>
        <div v-if="selectedNode?.related_edges?.length" class="detail-block">
          <div class="detail-label">关联关系 ({{ selectedNode?.related_edges.length }})</div>
          <div
            v-for="e in selectedNode?.related_edges"
            :key="e.id"
            class="related-edge"
            @click="handleEdgeClick(e)"
          >
            <span
              class="related-tag"
              :style="{ background: relationColors[e.relation_type] || '#C0C4CC' }"
            >
              {{ relationLabels[e.relation_type] || e.relation_type }}
            </span>
            <span class="related-target">
              ↔ {{ nodeTitle(e.source_node_id === selectedNode?.id ? e.target_node_id : e.source_node_id) }}
            </span>
            <span class="related-status">[{{ statusLabels[e.status] || e.status }}]</span>
          </div>
        </div>
      </div>

      <div v-else-if="selectedEdge" class="detail-section">
        <div class="detail-row">
          <span class="detail-label">类型</span>
          <span class="detail-value">
            {{ relationLabels[selectedEdge?.relation_type ?? ''] || selectedEdge?.relation_type }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">置信度</span>
          <span class="detail-value">
            {{ ((selectedEdge?.confidence ?? 0) * 100).toFixed(0) }}%
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">状态</span>
          <span class="detail-value">
            {{ statusLabels[selectedEdge?.status ?? ''] || selectedEdge?.status }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">源节点</span>
          <span class="detail-value">{{ nodeTitle(selectedEdge?.source_node_id ?? 0) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">目标节点</span>
          <span class="detail-value">{{ nodeTitle(selectedEdge?.target_node_id ?? 0) }}</span>
        </div>
        <div v-if="selectedEdge?.reason" class="detail-block">
          <div class="detail-label">生成理由</div>
          <div class="detail-text">{{ selectedEdge?.reason }}</div>
        </div>
        <div class="detail-actions">
          <el-button
            size="small"
            type="success"
            :disabled="selectedEdge?.status === 'confirmed'"
            @click="handleConfirm"
          >
            确认
          </el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="selectedEdge?.status === 'rejected'"
            @click="handleReject"
          >
            拒绝
          </el-button>
          <el-button size="small" type="primary" @click="handleCompare">
            生成对比
          </el-button>
        </div>
      </div>

      <div v-else class="empty-detail-text">
        点击节点或边查看详情
      </div>
    </el-drawer>

    <!-- Compare drawer -->
    <el-drawer
      v-model="compareDrawerVisible"
      title="跨课程概念对比报告"
      size="50%"
      direction="rtl"
    >
      <div v-loading="compareLoading">
        <div class="compare-focus-bar">
          <span class="focus-label">关注点：</span>
          <el-radio-group v-model="compareUserFocus" size="small" @change="handleCompare">
            <el-radio-button
              v-for="opt in userFocusOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="compareReport" class="compare-report">
          <el-alert
            v-if="compareReport.fallback_used"
            type="warning"
            :title="`使用 Mock fallback：${compareReport.fallback_reason || 'LLM 不可用'}`"
            :closable="false"
            show-icon
            class="compare-alert"
          />
          <el-alert
            v-else
            type="info"
            :title="`Provider: ${compareReport.provider} / Model: ${compareReport.model_name}`"
            :closable="false"
            show-icon
            class="compare-alert"
          />

          <div v-if="compareReport.citation_chunk_ids.length" class="report-section">
            <div class="section-title">
              证据来源 ({{ compareReport.citation_chunk_ids.length }} 个片段)
            </div>
            <div class="citation-list">
              <el-tag
                v-for="cid in compareReport.citation_chunk_ids"
                :key="cid"
                size="small"
                type="info"
                class="citation-tag"
              >
                Chunk #{{ cid }}
              </el-tag>
            </div>
          </div>
          <div v-else-if="compareReport.fallback_used" class="report-section">
            <el-alert
              type="warning"
              title="无证据片段：本次对比基于知识点摘要推断，未引用原始资料"
              :closable="false"
              show-icon
            />
          </div>

          <div v-if="compareReport.report_json.concept_a || compareReport.report_json.concept_b">
            <el-row :gutter="12" class="concept-row">
              <el-col :span="12">
                <div class="concept-card">
                  <div class="concept-title">
                    {{ compareReport.report_json.concept_a?.title || '-' }}
                  </div>
                  <div class="concept-explain">
                    {{ compareReport.report_json.concept_a?.explanation || '-' }}
                  </div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="concept-card">
                  <div class="concept-title">
                    {{ compareReport.report_json.concept_b?.title || '-' }}
                  </div>
                  <div class="concept-explain">
                    {{ compareReport.report_json.concept_b?.explanation || '-' }}
                  </div>
                </div>
              </el-col>
            </el-row>
          </div>

          <div v-if="compareReport.report_json.similarities?.length" class="report-section">
            <div class="section-title">相似点</div>
            <ul class="section-list">
              <li v-for="(s, i) in compareReport.report_json.similarities" :key="`s${i}`">
                {{ s }}
              </li>
            </ul>
          </div>

          <div v-if="compareReport.report_json.differences?.length" class="report-section">
            <div class="section-title">差异点</div>
            <el-table
              :data="compareReport.report_json.differences"
              size="small"
              border
              class="diff-table"
            >
              <el-table-column prop="dimension" label="维度" width="120" />
              <el-table-column prop="a" label="概念 A" />
              <el-table-column prop="b" label="概念 B" />
            </el-table>
          </div>

          <div v-if="compareReport.report_json.transfer_learning?.length" class="report-section">
            <div class="section-title">迁移应用</div>
            <ul class="section-list">
              <li v-for="(t, i) in compareReport.report_json.transfer_learning" :key="`t${i}`">
                {{ t }}
              </li>
            </ul>
          </div>

          <div v-if="compareReport.report_json.confusions?.length" class="report-section">
            <div class="section-title">易混点</div>
            <ul class="section-list">
              <li v-for="(c, i) in compareReport.report_json.confusions" :key="`c${i}`">
                {{ c }}
              </li>
            </ul>
          </div>

          <div v-if="compareReport.report_json.exam_questions?.length" class="report-section">
            <div class="section-title">考点</div>
            <ul class="section-list">
              <li v-for="(q, i) in compareReport.report_json.exam_questions" :key="`q${i}`">
                {{ q }}
              </li>
            </ul>
          </div>

          <div v-if="compareReport.report_json.insufficient_evidence" class="report-section">
            <el-alert
              type="warning"
              title="证据不足：当前缺少足够的证据片段，结果基于摘要推断"
              :closable="false"
              show-icon
            />
          </div>
        </div>
        <div v-else-if="!compareLoading" class="empty-detail-text">
          暂无对比报告
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.kg-page {
  height: calc(100vh - 100px);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* --- Toolbar --- */
.kg-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #fff;
  border-radius: 8px;
  padding: 10px 16px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.kg-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.kg-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.kg-stats {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

/* --- Canvas wrapper --- */
.kg-canvas-wrap {
  flex: 1 1 0;
  position: relative;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  overflow: hidden;
  min-height: 300px;
}

.graph-canvas {
  width: 100%;
  height: 100%;
  background:
    radial-gradient(circle at 1px 1px, rgba(64, 158, 255, 0.08) 1px, transparent 0);
  background-size: 24px 24px;
  border-radius: 8px;
}

/* --- Floating legend --- */
.kg-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  color: #606266;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  max-width: 200px;
  z-index: 10;
}

.legend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-weight: 600;
  color: #303133;
  cursor: pointer;
  user-select: none;
  margin-bottom: 4px;
}

.legend-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.legend-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.legend-subtitle {
  font-weight: 600;
  color: #303133;
  margin-bottom: 2px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-line {
  display: inline-block;
  width: 14px;
  height: 3px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* --- Empty overlay --- */
.empty-tip-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 8px;
  z-index: 5;
}

/* --- Detail drawer content --- */
.detail-section {
  padding: 0 4px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}

.detail-label {
  color: #909399;
}

.detail-value {
  color: #303133;
  font-weight: 500;
  text-align: right;
  max-width: 60%;
  word-break: break-all;
}

.detail-block {
  margin-top: 12px;
}

.detail-text {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 8px;
  font-size: 13px;
  color: #303133;
  margin-top: 4px;
  line-height: 1.6;
}

.related-edge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  color: #606266;
}

.related-edge:hover {
  color: #409eff;
}

.related-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  color: #fff;
  font-size: 11px;
}

.related-target {
  flex: 1;
}

.related-status {
  color: #909399;
  font-size: 11px;
}

.detail-actions {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.empty-detail-text {
  text-align: center;
  color: #909399;
  padding: 40px 0;
  line-height: 2;
}

/* --- Compare drawer --- */
.compare-report {
  padding: 0 8px;
}

.compare-focus-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 0 8px;
}

.focus-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}

.compare-alert {
  margin-bottom: 12px;
}

.concept-row {
  margin-bottom: 16px;
}

.concept-card {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 12px;
}

.concept-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}

.concept-explain {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.report-section {
  margin-top: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.section-list {
  margin: 0;
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}

.diff-table {
  margin-top: 4px;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.citation-tag {
  font-family: 'JetBrains Mono', monospace;
}

@media (max-width: 768px) {
  .kg-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .kg-filters {
    justify-content: center;
  }
  .kg-actions {
    justify-content: center;
  }
  .kg-legend {
    max-width: 160px;
    font-size: 11px;
  }
}
</style>
