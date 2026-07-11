import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia } from '../test/setup'
import KnowledgeGraphView from './KnowledgeGraphView.vue'
import type { GraphNode, GraphEdge } from '../api/conceptGraph'
import type { Course } from '../api/course'

// ---------------------------------------------------------------------------
// API mocks
// ---------------------------------------------------------------------------
vi.mock('../api/course', () => ({
  listCourses: vi.fn().mockResolvedValue({
    data: {
      items: [
        { id: 1, name: '操作系统', teacher: '张老师', semester: '2024', description: '', color: '#409eff' },
        { id: 2, name: '数据结构', teacher: '李老师', semester: '2024', description: '', color: '#67c23a' },
      ] as Course[],
      total: 2,
      page: 1,
      page_size: 100,
    },
  } as any),
}))

vi.mock('../api/conceptGraph', () => ({
  getGraph: vi.fn(),
  rebuildGraph: vi.fn(),
  getNodeDetail: vi.fn(),
  confirmEdge: vi.fn(),
  rejectEdge: vi.fn(),
  compareNodes: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockNodes: GraphNode[] = [
  {
    id: 1,
    user_id: 1,
    course_id: 1,
    knowledge_point_id: 1,
    title: '进程管理',
    normalized_title: '进程管理',
    summary: '进程管理是操作系统的核心功能',
    aliases: [],
    importance: 5,
    source_chunk_ids: [10, 11],
    weak_point_score: 2,
  },
  {
    id: 2,
    user_id: 1,
    course_id: 1,
    knowledge_point_id: 2,
    title: '内存管理',
    normalized_title: '内存管理',
    summary: '内存管理负责分配和回收内存',
    aliases: [],
    importance: 4,
    source_chunk_ids: [12],
    weak_point_score: 0,
  },
  {
    id: 3,
    user_id: 1,
    course_id: 2,
    knowledge_point_id: 3,
    title: '二叉树',
    normalized_title: '二叉树',
    summary: '二叉树是每个节点最多有两个子树的树结构',
    aliases: [],
    importance: 3,
    source_chunk_ids: [20],
    weak_point_score: 0,
  },
]

const mockEdges: GraphEdge[] = [
  {
    id: 1,
    user_id: 1,
    source_node_id: 1,
    target_node_id: 2,
    relation_type: 'prerequisite_of',
    confidence: 0.85,
    reason: '进程管理需要内存管理基础',
    evidence_chunk_ids: [10, 12],
    status: 'confirmed',
    audit_run_id: null,
  },
  {
    id: 2,
    user_id: 1,
    source_node_id: 1,
    target_node_id: 3,
    relation_type: 'similar_to',
    confidence: 0.42,
    reason: '可能存在概念相似性',
    evidence_chunk_ids: [],
    status: 'candidate',
    audit_run_id: null,
  },
]

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('KnowledgeGraphView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
  })

  it('renders node and edge stats with correct counts', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: mockNodes, edges: mockEdges } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Stats should show node count and edge count
    expect(html).toContain('3 节点')
    expect(html).toContain('2 关系')
  })

  it('renders legend with correct course colors and relation colors', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: mockNodes, edges: mockEdges } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Legend should contain course names
    expect(html).toContain('操作系统')
    expect(html).toContain('数据结构')

    // Legend should contain relation type labels
    expect(html).toContain('相似')
    expect(html).toContain('前置')
    expect(html).toContain('对比')
    expect(html).toContain('迁移应用')
    expect(html).toContain('同名异义')
    expect(html).toContain('易混')
    expect(html).toContain('上下位')

    // Legend should contain status labels
    expect(html).toContain('候选')
    expect(html).toContain('已确认')
  })

  it('renders sr-only text summary with node and edge details', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: mockNodes, edges: mockEdges } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Node summary should contain node titles, course names, and importance
    expect(html).toContain('进程管理')
    expect(html).toContain('内存管理')
    expect(html).toContain('二叉树')
    expect(html).toContain('重要度 5')
    expect(html).toContain('重要度 4')
    expect(html).toContain('重要度 3')

    // Edge summary should contain relation labels and status
    expect(html).toContain('进程管理')
    expect(html).toContain('内存管理')
    expect(html).toContain('前置')
    expect(html).toContain('已确认')
    expect(html).toContain('相似')
    expect(html).toContain('候选')
  })

  it('renders legend dots with correct background colors for courses', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: mockNodes, edges: mockEdges } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    // The courseColors computed maps course_id -> color from the palette:
    // ['#5B8FF9', '#5AD8A6', '#5D7092', ...]
    // course_id=1 -> '#5B8FF9' (rgb(91, 143, 249))
    // course_id=2 -> '#5AD8A6' (rgb(90, 216, 166))
    // Note: jsdom converts hex to rgb in style attributes
    const legendDots = wrapper.findAll('.legend-dot')
    expect(legendDots.length).toBeGreaterThanOrEqual(2)

    // First dot (course_id=1) should have background #5B8FF9 -> rgb(91, 143, 249)
    const dot1Style = legendDots[0].attributes('style') || ''
    expect(dot1Style).toContain('rgb(91, 143, 249)')

    // Second dot (course_id=2) should have background #5AD8A6 -> rgb(90, 216, 166)
    const dot2Style = legendDots[1].attributes('style') || ''
    expect(dot2Style).toContain('rgb(90, 216, 166)')
  })

  it('renders legend lines with correct relation colors', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: mockNodes, edges: mockEdges } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    // relationColors defines:
    // similar_to: '#67C23A' -> rgb(103, 194, 58)
    // contrast_with: '#E6A23C' -> rgb(230, 162, 60)
    // prerequisite_of: '#409EFF' -> rgb(64, 158, 255)
    // applies_to: '#909399' -> rgb(144, 147, 153)
    // same_name_different_meaning: '#F56C6C' -> rgb(245, 108, 108)
    // confused_with: '#9C27B0' -> rgb(156, 39, 176)
    // parent_of: '#00BCD4' -> rgb(0, 188, 212)
    // Note: jsdom converts hex to rgb in style attributes
    const legendLines = wrapper.findAll('.legend-line')
    expect(legendLines.length).toBeGreaterThanOrEqual(7)

    // Check that the prerequisite_of color (#409EFF -> rgb(64, 158, 255)) is present
    const allLineStyles = legendLines.map((l) => l.attributes('style') || '')
    const hasPrerequisiteColor = allLineStyles.some((s) => s.includes('rgb(64, 158, 255)'))
    expect(hasPrerequisiteColor).toBe(true)

    // Check that similar_to color (#67C23A -> rgb(103, 194, 58)) is present
    const hasSimilarColor = allLineStyles.some((s) => s.includes('rgb(103, 194, 58)'))
    expect(hasSimilarColor).toBe(true)
  })

  it('shows empty state when no graph data', async () => {
    const { getGraph } = await import('../api/conceptGraph')
    vi.mocked(getGraph).mockResolvedValue({ data: { nodes: [], edges: [] } } as any)

    const wrapper = mount(KnowledgeGraphView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Empty state should show "暂无图谱数据"
    expect(html).toContain('暂无图谱数据')
    // The legend should NOT be visible when there are no nodes
    expect(wrapper.findAll('.legend-dot').length).toBe(0)
  })
})
